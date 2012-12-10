# -*- coding: utf-8 -*-
"""
get_collection_attribute_view.py

A View to to get an attribute of a collection for a user
"""
from collections import namedtuple
import httplib
import json
import logging

import flask

from tools.greenlet_database_util import GetConnection
from tools.data_definitions import http_timestamp_str
from tools.customer_key_lookup import CustomerKeyConnectionLookup
from tools.collection import compute_default_collection_name

from web_collection_manager.connection_pool_view import ConnectionPoolView
from web_collection_manager.authenticator import authenticate

rules = ["/customers/<username>/collections/<collection_name>", ]
endpoint = "get_collection_attribute"

_short_day_query = """
SELECT 
        date_trunc('day', timestamp) as day,
        sum(retrieve_success),
        sum(archive_success),
        sum(listmatch_success),
        sum(delete_success),
        sum(success_bytes_in),
        sum(success_bytes_out)
  FROM nimbusio_central.collection_ops_accounting
 WHERE collection_id=%s
 GROUP BY day
 ORDER BY day desc
"""

_long_day_query = """
SELECT 
        date_trunc('day', timestamp) as day,
        sum(retrieve_success),
        sum(archive_success),
        sum(listmatch_success),
        sum(delete_success),
        sum(success_bytes_in),
        sum(success_bytes_out)
  FROM (select * from collection_ops_accounting
        UNION ALL
        select * from collection_ops_accounting_old) combined
 WHERE collection_id=%s
 GROUP BY day
 ORDER BY day desc
"""

_operational_stats_row = namedtuple("OperationalStatsRow", [
        "day",
        "retrieve_success",
        "archive_success",
        "listmatch_success",
        "delete_success",
        "success_bytes_in",
        "success_bytes_out"])

def _list_collection(cursor, customer_id, collection_name):
    """
    list a named collection for the customer
    """
    cursor.execute("""
        select name, versioning, access_control, creation_time 
        from nimbusio_central.collection   
        where customer_id = %s and name = %s and deletion_time is null
        """, [customer_id, collection_name])
    result = cursor.fetchone()

    return result

def _get_collection_info(cursor, username, customer_id, collection_name):
    """
    get basic information about the collection
    See Ticket #51 Implement GET JSON for a collection
    """
    log = logging.getLogger("_get_collection_info")
    log.debug("_list_collection(cursor, {0}, {1}".format(customer_id, collection_name))
    row = _list_collection(cursor, customer_id, collection_name)
    if row is None:
        collection_dict = {"success"       : False, 
                           "error_message" : "No such collection"}
        return httplib.NOT_FOUND, collection_dict

    default_collection_name = compute_default_collection_name(username)

    name, versioning, raw_access_control, raw_creation_time = row
    if raw_access_control is None:
        access_control = None
    else:
        access_control = json.loads(raw_access_control)
    collection_dict = {"success" : True,
                       "name" : name, 
                       "default_collection" : name == default_collection_name,
                       "versioning" : versioning, 
                       "access_control" : access_control,
                       "creation-time" : http_timestamp_str(raw_creation_time)}
    return httplib.OK, collection_dict

def _get_collection_id(cursor, customer_id, collection_name):
    """
    get the id of a named collection for the customer
    """
    cursor.execute("""
        select id
        from nimbusio_central.collection   
        where customer_id = %s and name = %s
        """, [customer_id, collection_name])
    result = cursor.fetchone()
    if result is None:
        return None

    return result[0]

def _get_collection_space_usage(cursor, customer_id, collection_name, args):
    """
    get usage information for the collection
    See Ticket #66 Include operational stats in API queries for space usage
    """
    log = logging.getLogger("_get_collection_space_usage")

    collection_id = _get_collection_id(cursor, customer_id, collection_name)
    if collection_id is None:
        collection_dict = {"success"       : False, 
                           "error_message" : "No such collection"}
        return httplib.NOT_FOUND, collection_dict

    # 2012-12-10 dougfort -- for reasons I don't understand, success_bytes_in
    # and success_bytes_out emerge as type Dec. So I force them to int to
    # keep JSON happy.
    
    cursor.execute(_short_day_query, [collection_id, ])
    collection_dict = {"success" : True, "operational_stats" : list()}
    for row in map(_operational_stats_row._make, cursor.fetchall()):
        stats_dict =  { "day" : http_timestamp_str(row.day),
            "retrieve_success" : row.retrieve_success,
            "archive_success"  : row.archive_success,
            "listmatch_success": row.listmatch_success,
            "delete_success"   : row.delete_success,
            "success_bytes_in" : int(row.success_bytes_in),
            "success_bytes_out": int(row.success_bytes_out), }
        collection_dict["operational_stats"].append(stats_dict)

    return httplib.OK, collection_dict

class GetCollectionAttributeView(ConnectionPoolView):
    methods = ["GET", ]

    def dispatch_request(self, username, collection_name):
        log = logging.getLogger("GetCollectionAttributeView")

        log.info("user_name = {0}, collection_name = {1}".format(
            username, collection_name))

        result_dict = None

        with GetConnection(self.connection_pool) as connection:

            customer_key_lookup = \
                CustomerKeyConnectionLookup(self.memcached_client,
                                            connection)
            customer_id = authenticate(customer_key_lookup,
                                       username,
                                       flask.request)
            if customer_id is None:
                flask.abort(httplib.UNAUTHORIZED)

            cursor = connection.cursor()
            if "action" in  flask.request.args:
                assert flask.request.args["action"] == "space_usage"
                handler = _get_collection_space_usage
                try:
                    status, result_dict = handler(cursor, 
                                                  customer_id,
                                                  collection_name, 
                                                  flask.request.args)
                except Exception:
                    log.exception("{0} {1}".format(collection_name, 
                                                   flask.request.args))
                    cursor.close()
                    raise
            else:
                handler = _get_collection_info
                try:
                    status, result_dict = handler(cursor, 
                                                  username,
                                                  customer_id,
                                                  collection_name)
                except Exception:
                    log.exception("{0} {1}".format(collection_name, 
                                                   flask.request.args))
                    cursor.close()
                    raise
            cursor.close()


        # Ticket #33 Make Nimbus.io API responses consistently JSON
        return flask.Response(json.dumps(result_dict, 
                                         sort_keys=True, 
                                         indent=4), 
                              status=status,
                              content_type="application/json")

view_function = GetCollectionAttributeView.as_view(endpoint)

