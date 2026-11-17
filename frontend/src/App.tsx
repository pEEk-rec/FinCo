import { Navigate, Route, Routes, useLocation } from 'react-router';

import { Shell } from './components/Shell';
import { AskScreen } from './screens/Ask';
import { DashboardScreen } from './screens/Dashboard';
import { DesignScreen } from './screens/Design';
import { PlanScreen } from './screens/Plan';
import { ReviewScreen } from './screens/Review';
import { SettingsScreen } from './screens/Settings';
import { TransactionsScreen } from './screens/Transactions';
import { WelcomeScreen } from './screens/Welcome';
import { useDemoMode } from './state/demo';

/**
 * An old address keeps working: it lands on the feature's one new home, keeping its query
 * (a notification's ?prompt=, a link's ?period=) and adding the tab it now lives under.
 */
function MovedTo({ to, tab }: { to: string; tab?: string }) {
  const { search } = useLocation();
  const params = new URLSearchParams(search);
  if (tab) params.set('tab', tab);
  const query = params.toString();
  return <Navigate to={`${to}${query ? `?${query}` : ''}`} replace />;
}

function DemoOnly() {
  return useDemoMode() ? <DesignScreen /> : <Navigate to="/" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/welcome" element={<WelcomeScreen />} />
      <Route element={<Shell />}>
        <Route index element={<DashboardScreen />} />
        <Route path="transactions" element={<TransactionsScreen />} />
        <Route path="review" element={<ReviewScreen />} />
        <Route path="plan" element={<PlanScreen />} />
        <Route path="ask" element={<AskScreen />} />
        <Route path="settings" element={<SettingsScreen />} />
        <Route path="design" element={<DemoOnly />} />

        {/* Where things used to be */}
        <Route path="today" element={<MovedTo to="/review" />} />
        <Route path="capture" element={<MovedTo to="/review" />} />
        <Route path="agent" element={<MovedTo to="/ask" />} />
        <Route path="monthly" element={<MovedTo to="/plan" tab="review" />} />
        <Route path="for-you" element={<MovedTo to="/plan" tab="budget" />} />
        <Route path="goals" element={<MovedTo to="/plan" tab="goals" />} />
        <Route path="challenges" element={<MovedTo to="/plan" tab="challenges" />} />
        <Route path="progress" element={<MovedTo to="/plan" tab="challenges" />} />
        <Route path="connect" element={<MovedTo to="/settings" tab="connections" />} />
        <Route path="live" element={<MovedTo to="/settings" tab="connections" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
