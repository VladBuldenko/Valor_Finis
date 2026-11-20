# Shared bounds for the opt-in pagination of the Expenses and Income lists
# (VF-MVP-BETA-001). The rule lists keep their own (20 / 100) literals; this
# module only serves the two lists that stay backward compatible, where a
# request WITHOUT limit/offset must keep returning the bare, complete list.

# Page size used when the client asks for pagination with offset alone.
DEFAULT_PAGE_LIMIT = 50

# Largest page a client may request; larger values are rejected (422), not
# silently clamped, so a client never believes it received a page it did not.
MAX_PAGE_LIMIT = 100
