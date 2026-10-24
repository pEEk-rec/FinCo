import { Route, Routes } from 'react-router';

import { Shell } from './components/Shell';
import { AgentScreen } from './screens/Agent';
import { CaptureScreen } from './screens/Capture';
import { ChallengesScreen } from './screens/Challenges';
import { TodayScreen } from './screens/Today';
import { ConnectScreen } from './screens/Connect';
import { DashboardScreen } from './screens/Dashboard';
import { DesignScreen } from './screens/Design';
import { GoalsScreen } from './screens/Goals';
import { LiveScreen } from './screens/Live';
import { MonthlyScreen } from './screens/Monthly';
import { ProgressScreen } from './screens/Progress';
import { ReviewScreen } from './screens/Review';
import { TransactionsScreen } from './screens/Transactions';
import { WelcomeScreen } from './screens/Welcome';

export function App() {
  return (
    <Routes>
      <Route path="/welcome" element={<WelcomeScreen />} />
      <Route element={<Shell />}>
        <Route index element={<DashboardScreen />} />
        <Route path="transactions" element={<TransactionsScreen />} />
        <Route path="review" element={<ReviewScreen />} />
        <Route path="capture" element={<CaptureScreen />} />
        <Route path="today" element={<TodayScreen />} />
        <Route path="goals" element={<GoalsScreen />} />
        <Route path="challenges" element={<ChallengesScreen />} />
        <Route path="progress" element={<ProgressScreen />} />
        <Route path="monthly" element={<MonthlyScreen />} />
        <Route path="agent" element={<AgentScreen />} />
        <Route path="connect" element={<ConnectScreen />} />
        <Route path="live" element={<LiveScreen />} />
        <Route path="design" element={<DesignScreen />} />
      </Route>
    </Routes>
  );
}
