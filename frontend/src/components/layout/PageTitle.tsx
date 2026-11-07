import { APP_NAME } from '@/appName'

// React puts a <title> rendered anywhere into the document head, so each page
// names itself in the browser tab and to screen readers
export default function PageTitle({ children }: { children?: string }) {
  return <title>{children ? `${children} | ${APP_NAME}` : APP_NAME}</title>
}
