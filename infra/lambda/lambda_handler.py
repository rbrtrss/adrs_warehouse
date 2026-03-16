import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    from adrs_warehouse.data.fetch import update_warehouse
    from adrs_warehouse.database.operations import create_database

    # Set up adrs_warehouse logger with StreamHandler BEFORE calling update_warehouse.
    # setup_logging() in fetch.py is idempotent: it returns early if a non-NullHandler
    # exists, so this prevents it from trying to create logs/ in read-only /var/task/.
    aw_logger = logging.getLogger("adrs_warehouse")
    aw_logger.setLevel(logging.DEBUG)
    aw_logger.addHandler(logging.StreamHandler())

    db = create_database(
        "motherduck",
        database=os.environ.get("MOTHERDUCK_DB", "adrs_warehouse"),
    )
    try:
        stats = update_warehouse(db=db)
    except Exception as exc:
        logger.exception("Warehouse update failed: %s", exc)
        raise  # Lambda marks as error → triggers CloudWatch alarm
    logger.info("Update complete — %s", stats)
    return {"statusCode": 200, "body": json.dumps(stats)}
