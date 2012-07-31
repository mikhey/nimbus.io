class AlreadyInProgress(Exception):
    pass

class CollectionError(Exception):
    pass

class RetrieveFailedError(Exception):
    pass

class ListmatchFailedError(Exception):
    pass

class SpaceUsageFailedError(Exception):
    pass

class StatFailedError(Exception):
    pass

class DataReaderDownError(Exception):
    pass

class DatabaseServerDownError(Exception):
    pass

class SpaceAccountingServerDownError(Exception):
    pass

class ConjoinedFailedError(Exception):
    pass

