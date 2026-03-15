import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import BracketView from './pages/BracketView'
import DebateView from './pages/DebateView'
import AgentLeaderboard from './pages/AgentLeaderboard'
import UpsetWatch from './pages/UpsetWatch'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/bracket" element={<BracketView />} />
          <Route path="/debate/:gameId" element={<DebateView />} />
          <Route path="/agents" element={<AgentLeaderboard />} />
          <Route path="/upsets" element={<UpsetWatch />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
