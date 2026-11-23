// A number of hours, as the emails say it (hours() in
// backend/app/auth/emails.py), so a page and its email name a link's
// lifetime alike
export function hours(count: number) {
  return `${count} hour${count === 1 ? '' : 's'}`
}
