import { AnimatePresence, motion, useReducedMotion } from 'motion/react';

import { useDashboard } from '../api/hooks';
import { Card } from '../components/Card';
import { Embedded, Page } from '../components/Shell';
import { SkeletonBlock } from '../components/States';
import { Tabs, useTabParam, type TabDef } from '../components/Tabs';
import { copy } from '../copy/en';
import { useMonth } from '../state/month';
import { ChallengesScreen } from './Challenges';
import { UpcomingCard } from './Dashboard';
import { BudgetCard, SubscriptionsCard } from './ForYou';
import { GoalsScreen } from './Goals';
import { MonthlyScreen } from './Monthly';
import { ProgressScreen } from './Progress';

type Tab = 'review' | 'budget' | 'goals' | 'bills' | 'challenges';
const TABS: TabDef<Tab>[] = [
  { id: 'review', label: 'Monthly review' },
  { id: 'budget', label: 'Budget' },
  { id: 'goals', label: 'Goals' },
  { id: 'bills', label: 'Bills and subscriptions' },
  { id: 'challenges', label: 'Challenges' },
];

function Bills() {
  const { month } = useMonth();
  const dashboard = useDashboard(month);
  return (
    <div className="grid items-start gap-5 lg:grid-cols-2">
      {dashboard.data ? (
        <UpcomingCard data={dashboard.data} />
      ) : (
        <Card className="p-6">
          <SkeletonBlock lines={4} />
        </Card>
      )}
      <SubscriptionsCard />
    </div>
  );
}

/** Everything forward-looking, in one place: the month's review, the plan, goals, bills, habits. */
export function PlanScreen() {
  const [tab, setTab] = useTabParam(TABS, 'review');
  const reduce = useReducedMotion();
  return (
    <Page title={copy.plan.title} lead={copy.plan.lead} wide>
      <Tabs id="plan" label={copy.plan.title} tabs={TABS} value={tab} onChange={setTab} />
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          role="tabpanel"
          initial={reduce ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduce ? undefined : { opacity: 0, y: -4 }}
          transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
          className="pt-6"
        >
          <Embedded>
            {tab === 'review' ? <MonthlyScreen /> : null}
            {tab === 'budget' ? <BudgetCard /> : null}
            {tab === 'goals' ? <GoalsScreen /> : null}
            {tab === 'bills' ? <Bills /> : null}
            {tab === 'challenges' ? (
              <div className="flex flex-col gap-10">
                <ChallengesScreen />
                <ProgressScreen />
              </div>
            ) : null}
          </Embedded>
        </motion.div>
      </AnimatePresence>
    </Page>
  );
}
