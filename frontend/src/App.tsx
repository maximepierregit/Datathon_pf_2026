import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Splash } from './components/Splash'
import Dashboard from './pages/dashboard/Dashboard'
import Home from './pages/Home'
import Pipeline from './pages/Pipeline'
import Preferences from './pages/Preferences'
import Profile from './pages/Profile'
import Transition from './pages/Transition'
import Verification from './pages/Verification'

export default function App() {
  return (
    <>
      <Splash />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="profil/:step" element={<Profile />} />
          <Route path="transition" element={<Transition />} />
          <Route path="preferences/:step" element={<Preferences />} />
          <Route path="verification" element={<Verification />} />
          <Route path="construction" element={<Pipeline />} />
          <Route path="portefeuille" element={<Dashboard />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </>
  )
}
