import { Link } from 'react-router-dom'
import PageTitle from '@/components/layout/PageTitle'

export default function NotFoundPage() {
  return (
    <div className="message-page">
      <PageTitle>Page not found</PageTitle>
      <h1>Page not found</h1>
      <p>There is nothing at this address.</p>
      <Link to="/" className="btn btn-primary">Go home</Link>
    </div>
  )
}
