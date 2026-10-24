"""Conservative duplicate evidence; records and provider attribution stay intact."""


def duplicate_groups(records):
    buckets = {}
    for record in records:
        # Kind is part of identity: adaptations and editions are not interchangeable.
        for namespace, value in record.external_ids.items():
            key = (record.kind, namespace, value)
            buckets.setdefault(key, set()).add(record.id)
    # Return direct shared-ID evidence, not transitive title-based merge instructions.
    return [
        {"kind": kind, "namespace": namespace, "external_id": value, "record_ids": sorted(ids)}
        for (kind, namespace, value), ids in buckets.items()
        if len(ids) > 1
    ]
