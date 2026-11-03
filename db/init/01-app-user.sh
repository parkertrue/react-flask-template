#!/bin/sh
# Creates the app's MySQL user, which may read and write rows but never change
# the schema. Every compose file mounts this into the MySQL image's
# /docker-entrypoint-initdb.d, which runs it once, when the data volume is
# first created: after the image has made MYSQL_DATABASE and MYSQL_USER (the
# migration user, which owns the schema) and before it accepts connections
# from outside. To change a user later, see docs/deployment.md, "Changing a Value Later".
#
# The image sources this file, or runs it when it is executable (as files
# mounted from Windows are), so it relies on none of the image's own shell
# functions and does its work in a subshell, whose failure stops the image's
# entrypoint either way.
(
  set -eu

  fail() {
    echo "01-app-user.sh: $1" >&2
    exit 1
  }

  # .env.prod.example's placeholders must never reach a database. The root
  # password is checked here alone: nothing else ever holds it.
  for password in "$DB_PASSWORD" "$MYSQL_PASSWORD" "$MYSQL_ROOT_PASSWORD"; do
    case "$password" in
      your_*_here) fail 'a password is still the .env.prod.example placeholder' ;;
    esac
  done
  [ "$DB_USER" != "$MYSQL_USER" ] ||
    fail 'DB_USER and DB_MIGRATION_USER must be different users'
  # Identifiers cannot be quoted like values, so allow only names that are
  # safe between backticks
  case "$MYSQL_DATABASE" in
    '' | *[!A-Za-z0-9_]*) fail "unexpected database name: $MYSQL_DATABASE" ;;
  esac

  # A SQL string literal: backslashes doubled, quotes doubled
  literal() {
    printf "'%s'" "$(printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/''/g")"
  }
  # In GRANT, `_` in a database name is a wildcard that would match other
  # databases too, so escape it as the image does for MYSQL_USER's grant
  database=$(printf '%s' "$MYSQL_DATABASE" | sed 's/_/\\_/g')
  user="$(literal "$DB_USER")@'%'"

  MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot <<SQL
CREATE USER $user IDENTIFIED BY $(literal "$DB_PASSWORD");
GRANT SELECT, INSERT, UPDATE, DELETE ON \`$database\`.* TO $user;
SQL
  echo "01-app-user.sh: $DB_USER may read and write rows in $MYSQL_DATABASE"
)
