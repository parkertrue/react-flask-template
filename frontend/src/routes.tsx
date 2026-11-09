import Layout from '@/components/layout/Layout'
import GuestRoute from '@/auth/GuestRoute'
import ProtectedRoute from '@/auth/ProtectedRoute'
import HomePage from '@/pages/HomePage'
import LoginPage from '@/pages/LoginPage'
import RegisterPage from '@/pages/RegisterPage'
import CompleteRegistrationPage from '@/pages/CompleteRegistrationPage'
import AccountPage from '@/pages/AccountPage'
import PrivacyPage from '@/pages/PrivacyPage'
import TermsPage from '@/pages/TermsPage'
import ContactPage from '@/pages/ContactPage'
import NotFoundPage from '@/pages/NotFoundPage'
import ErrorPage from '@/pages/ErrorPage'
import NotesPage from '@/features/notes/NotesPage'
import type { RouteObject } from 'react-router-dom'

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <Layout />,
    // A crash in the layout itself: the error page replaces everything, so
    // it brings its own <main> landmark
    errorElement: <main><ErrorPage /></main>,
    children: [
      {
        // A crash in a page: the error page takes its place under the navbar
        errorElement: <ErrorPage />,
        children: [
          { index: true, element: <HomePage /> },
          // Public whether signed in or not
          { path: 'privacy', element: <PrivacyPage /> },
          { path: 'terms', element: <TermsPage /> },
          { path: 'contact', element: <ContactPage /> },
          {
            element: <GuestRoute />,
            children: [
              { path: 'login', element: <LoginPage /> },
              { path: 'register', element: <RegisterPage /> },
              // The emailed link's page
              { path: 'register/complete', element: <CompleteRegistrationPage /> },
            ],
          },
          {
            element: <ProtectedRoute />,
            children: [
              { path: 'notes', element: <NotesPage /> },
              { path: 'account', element: <AccountPage /> },
            ],
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
]
