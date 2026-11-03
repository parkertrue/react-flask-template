# The largest id an INT primary key holds. Every id in a URL or a cursor is
# one, so anything past this is malformed and refused before any query.
# MySQL would just find nothing, but SQLite's driver fails on a number past
# 2**63 and answers 500, so the bound keeps every database's answer the same.
ID_MAX = 2**31 - 1
