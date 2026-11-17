import { Link } from 'react-router';

import { useCaptureInbox, useSession } from '../api/hooks';
import { Card } from '../components/Card';
import { Embedded, Page } from '../components/Shell';
import { SkeletonBlock } from '../components/States';
import { Tabs, useTabParam, type TabDef } from '../components/Tabs';
import { copy } from '../copy/en';
import { BankLink } from '../components/BankLink';
import { useDemoMode } from '../state/demo';
import { BridgeCard, NotificationsCard, SimulatorPanel } from './Capture';
import { ConnectScreen } from './Connect';
import { AboutYouCard } from './ForYou';
import { LiveScreen } from './Live';

type Tab = 'you' | 'connections' | 'notifications' | 'demo';

function Simulator() {
  const inbox = useCaptureInbox();
  return inbox.data ? (
    <SimulatorPanel inbox={inbox.data} />
  ) : (
    <Card className="p-6">
      <SkeletonBlock lines={4} />
    </Card>
  );
}

/** Rarely visited: who you are to FinCo, how your money gets in, and how FinCo reaches you. */
export function SettingsScreen() {
  const demo = useDemoMode();
  const session = useSession();
  const tabs: TabDef<Tab>[] = [
    { id: 'you', label: 'About you' },
    { id: 'connections', label: 'Connections' },
    { id: 'notifications', label: 'Notifications' },
    ...(demo ? [{ id: 'demo' as const, label: 'Demo tools' }] : []),
  ];
  const [tab, setTab] = useTabParam(tabs, 'you');
  return (
    <Page title={copy.nav.settings} lead={copy.settings.lead}>
      <Tabs id="settings" label={copy.nav.settings} tabs={tabs} value={tab} onChange={setTab} />
      <div role="tabpanel" className="max-w-3xl pt-6">
        <Embedded>
          {tab === 'you' ? <AboutYouCard /> : null}
          {tab === 'connections' ? (
            <div className="flex flex-col gap-10">
              <ConnectScreen />
              {session.data?.data_source === 'connected' ? <LiveScreen /> : null}
              <BridgeCard />
            </div>
          ) : null}
          {tab === 'notifications' ? <NotificationsCard /> : null}
          {tab === 'demo' ? (
            <div className="flex flex-col gap-5">
              <Simulator />
              <BankLink />
              <p className="text-small text-ink-3">
                {copy.settings.designLead}{' '}
                <Link to="/design" className="text-brand underline underline-offset-2">
                  {copy.settings.designLink}
                </Link>
              </p>
            </div>
          ) : null}
        </Embedded>
      </div>
    </Page>
  );
}
