// The signed-in account (GET /api/account) in the query cache: AccountPage
// shows it, and an email change's page reads it again once the address moves.
// AuthProvider empties the cache when the signed-in account changes.
export const ACCOUNT_QUERY_KEY = ['account']
