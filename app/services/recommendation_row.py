"""RecommendationRow service for filter criteria validation and application."""

from typing import Any

from sqlalchemy import Select, asc, desc

from app.models import MediaFile

# Whitelist of allowed fields for ordering and filtering
ALLOWED_ORDER_FIELDS = {
    "scanned_at",
    "created_at",
    "updated_at",
    "duration",
    "file_name",
    "file_size",
    "width",
    "height",
    "bitrate",
}

# Whitelist of allowed fields for filtering
ALLOWED_FILTER_FIELDS = {
    "scanned_at",
    "created_at",
    "updated_at",
    "duration",
    "file_name",
    "file_size",
    "file_extension",
    "width",
    "height",
    "codec",
    "bitrate",
}


def validate_order_by(field: str) -> None:
    """Validate that order_by field is in the whitelist.

    Args:
        field: Field name to validate

    Raises:
        ValueError: If field is not in the whitelist
    """
    if field not in ALLOWED_ORDER_FIELDS:
        raise ValueError(
            f"Invalid order_by field: {field}. Allowed fields: {sorted(ALLOWED_ORDER_FIELDS)}"
        )


def validate_filter_field(field: str) -> None:
    """Validate that filter field is in the whitelist.

    Args:
        field: Field name to validate

    Raises:
        ValueError: If field is not in the whitelist
    """
    if field not in ALLOWED_FILTER_FIELDS:
        raise ValueError(
            f"Invalid filter field: {field}. Allowed fields: {sorted(ALLOWED_FILTER_FIELDS)}"
        )


def parse_where_clause(where_clause: list[dict[str, Any]]) -> list[Any]:  # noqa: C901
    """Parse and validate where clause filters.

    Args:
        where_clause: List of filter dictionaries with format:
            [{"field": "duration", "operator": "gt", "value": 3600}, ...]

    Returns:
        List of SQLAlchemy filter expressions

    Raises:
        ValueError: If filter is invalid or field not allowed
    """
    filters = []

    for filter_item in where_clause:
        if not isinstance(filter_item, dict):
            raise ValueError("Each where clause item must be a dictionary")

        field = filter_item.get("field")
        operator = filter_item.get("operator")
        value = filter_item.get("value")

        if not field or not operator:
            raise ValueError("Filter must have 'field' and 'operator' keys")

        validate_filter_field(field)

        # Get the column attribute
        column = getattr(MediaFile, field, None)
        if column is None:
            raise ValueError(f"Field {field} does not exist on MediaFile")

        # Apply operator
        if operator == "eq":
            filters.append(column == value)
        elif operator == "ne":
            filters.append(column != value)
        elif operator == "gt":
            filters.append(column > value)
        elif operator == "gte":
            filters.append(column >= value)
        elif operator == "lt":
            filters.append(column < value)
        elif operator == "lte":
            filters.append(column <= value)
        elif operator == "like":
            if not isinstance(value, str):
                raise ValueError("LIKE operator requires string value")
            filters.append(column.like(value))
        elif operator == "ilike":
            if not isinstance(value, str):
                raise ValueError("ILIKE operator requires string value")
            filters.append(column.ilike(value))
        elif operator == "in":
            if not isinstance(value, list):
                raise ValueError("IN operator requires list value")
            filters.append(column.in_(value))
        elif operator == "not_in":
            if not isinstance(value, list):
                raise ValueError("NOT IN operator requires list value")
            filters.append(~column.in_(value))
        elif operator == "is_null":
            filters.append(column.is_(None))
        elif operator == "is_not_null":
            filters.append(column.isnot(None))
        else:
            raise ValueError(f"Unsupported operator: {operator}")

    return filters


def apply_filter_criteria(
    query: Select[tuple[MediaFile]],
    filter_criteria: dict[str, Any],
    library_path: str,
) -> Select[tuple[MediaFile]]:
    """Apply filter criteria to a MediaFile query.

    Args:
        query: Base SQLAlchemy select query for MediaFile
        filter_criteria: Dictionary with filter criteria:
            - order_by: Field name to order by
            - order: "ASC" or "DESC"
            - limit: Maximum number of results
            - offset: Number of results to skip
            - where: List of filter dictionaries
        library_path: Library path to filter by (file_path must start with this)

    Returns:
        Modified query with filters applied

    Raises:
        ValueError: If filter criteria is invalid
    """
    # Always filter by library path and exclude deleted files
    query = query.where(
        MediaFile.file_path.startswith(library_path),
        MediaFile.deleted_at.is_(None),
    )

    # Apply where clauses if present
    if filter_criteria.get("where"):
        where_filters = parse_where_clause(filter_criteria["where"])
        for where_filter in where_filters:
            query = query.where(where_filter)

    # Apply ordering
    if "order_by" in filter_criteria:
        order_field = filter_criteria["order_by"]
        validate_order_by(order_field)

        column = getattr(MediaFile, order_field)
        order_direction = filter_criteria.get("order", "ASC").upper()

        if order_direction == "DESC":
            query = query.order_by(desc(column))
        else:
            query = query.order_by(asc(column))

    # Apply limit
    if "limit" in filter_criteria:
        limit = filter_criteria["limit"]
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        query = query.limit(limit)

    # Apply offset
    if "offset" in filter_criteria:
        offset = filter_criteria["offset"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        query = query.offset(offset)

    return query


def validate_filter_criteria(filter_criteria: dict[str, Any]) -> None:
    """Validate filter criteria without applying it.

    Args:
        filter_criteria: Dictionary with filter criteria

    Raises:
        ValueError: If filter criteria is invalid
    """
    # Validate order_by if present
    if "order_by" in filter_criteria:
        validate_order_by(filter_criteria["order_by"])

    # Validate order direction if present
    if "order" in filter_criteria:
        order = filter_criteria["order"].upper()
        if order not in ("ASC", "DESC"):
            raise ValueError("order must be 'ASC' or 'DESC'")

    # Validate where clauses if present
    if filter_criteria.get("where"):
        parse_where_clause(filter_criteria["where"])

    # Validate limit if present
    if "limit" in filter_criteria:
        limit = filter_criteria["limit"]
        if not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")

    # Validate offset if present
    if "offset" in filter_criteria:
        offset = filter_criteria["offset"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
