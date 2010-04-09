# -*- coding: utf-8 -*-
"""
diyapi_handoff_server_main.py

"""
import logging
import os
import sys
import time

from diyapi_tools import amqp_connection
from diyapi_tools import message_driven_process as process
from diyapi_tools.standard_logging import format_timestamp 

from messages.process_status import ProcessStatus

from messages.hinted_handoff import HintedHandoff
from messages.hinted_handoff_reply import HintedHandoffReply

from diyapi_data_writer.diyapi_data_writer_main import _routing_header \
        as data_writer_routing_header

from diyapi_handoff_server.hint_repository import HintRepository

_log_path = u"/var/log/pandora/diyapi_handoff_server_%s.log" % (
    os.environ["SPIDEROAK_MULTI_NODE_NAME"],
)
_queue_name = "handoff-server-%s" % (os.environ["SPIDEROAK_MULTI_NODE_NAME"], )
_routing_header = "handoff_server"
_routing_key_binding = ".".join([_routing_header, "*"])

def _handle_hinted_handoff(state, message_body):
    log = logging.getLogger("_handle_hinted_handoff")
    message = HintedHandoff.unmarshall(message_body)
    log.info("avatar_id %s, key %s, version_number %s, segment_number %s" % (
        message.avatar_id, 
        message.key,  
        message.version_number, 
        message.segment_number
    ))

    reply_exchange = message.reply_exchange
    reply_routing_key = "".join(
        [message.reply_routing_header, ".", HintedHandoffReply.routing_tag]
    )

    try:
        state["hint-repository"].store(
            message.dest_exchange,
            message.timestamp,
            message.key,
            message.version_number,
            message.segment_number
        )
    except Exception, instance:
        log.exception(str(instance))
        reply = HintedHandoffReply(
            message.request_id,
            HintedHandoffReply.error_exception,
            error_message=str(instance)
        )
        return [(reply_exchange, reply_routing_key, reply, )]

    reply = HintedHandoffReply( 
        message.request_id, HintedHandoffReply.successful
    )
    return [(reply_exchange, reply_routing_key, reply, )]

def _handle_process_status(state, message_body):
    log = logging.getLogger("_handle_process_status")
    message = ProcessStatus.unmarshall(message_body)
    log.debug("%s %s %s %s" % (
        message.exchange,
        message.routing_header,
        message.status,
        format_timestamp(message.timestamp),
    ))
    
    # we're interested in startup messages from data_writers
    # for whom we may have handoffs
    if message.routing_header == data_writer_routing_header \
       and message.status == ProcessStatus.status_startup:
        results = _check_for_handoffs(state, message.exchange)
    else:
        results = []

    return results

_dispatch_table = {
    HintedHandoff.routing_key       : _handle_hinted_handoff,
    ProcessStatus.routing_key       : _handle_process_status,
}

def _check_for_handoffs(state, dest_exchange):
    """
    initiate the the process of retrieving handoffs and sending them to
    the data_writer at the destination_exchange
    """
    log = logging.getLogger("_start_returning_handoffs")
    hint = state["hint-repository"].next_hint(dest_exchange)
    if hint is None:
        return []
    log.debug("found hint for exchange = %s" % (dest_exchange, ))
    return []

def _startup(_halt_event, state):
    state["hint-repository"] = HintRepository()

    message = ProcessStatus(
        time.time(),
        amqp_connection.local_exchange_name,
        _routing_header,
        ProcessStatus.status_startup
    )

    exchange = amqp_connection.broadcast_exchange_name
    routing_key = ProcessStatus.routing_key

    return [(exchange, routing_key, message, )]

def _shutdown(state):
    state["hint-repository"].close()
    del state["hint-repository"]

    message = ProcessStatus(
        time.time(),
        amqp_connection.local_exchange_name,
        _routing_header,
        ProcessStatus.status_shutdown
    )

    exchange = amqp_connection.broadcast_exchange_name
    routing_key = ProcessStatus.routing_key

    return [(exchange, routing_key, message, )]

if __name__ == "__main__":
    state = dict()
    sys.exit(
        process.main(
            _log_path, 
            _queue_name, 
            _routing_key_binding, 
            _dispatch_table, 
            state,
            pre_loop_function=_startup,
            in_loop_function=None,
            post_loop_function=_shutdown
        )
    )
