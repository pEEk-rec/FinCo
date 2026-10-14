import { Badge, CategoryPill, Chip, SourceBadge } from '../components/Badge';
import { Button } from '../components/Button';
import { Card, CardHeader, Stat } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, InsufficientDataState, SkeletonBlock } from '../components/States';
import { copy } from '../copy/en';
import { formatINR } from '../format/money';
import { colors, categoryPalette } from '../tokens/tokens';

/** Kitchen sink: tokens, type scale and every component state in one place. */
export function DesignScreen() {
  return (
    <Page title="Design system" lead="Tokens, type and component states.">
      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader label="Colour tokens" />
          <ul className="grid grid-cols-2 gap-3 p-6 sm:grid-cols-4 lg:grid-cols-7">
            {Object.keys(colors).map((name) => (
              <li key={name} className="flex flex-col gap-1.5">
                <span
                  className="h-10 rounded-control border border-hairline"
                  style={{ backgroundColor: `var(--color-${name})` }}
                />
                <span className="text-small text-ink-2">{name}</span>
              </li>
            ))}
          </ul>
          <ul className="flex flex-wrap gap-2 px-6 pb-6">
            {categoryPalette.map((_, i) => (
              <li key={i}>
                <CategoryPill categoryId={`cat-${i}`} name={`Category ${i + 1}`} />
              </li>
            ))}
          </ul>
        </Card>
        <Card>
          <CardHeader label="Type" />
          <div className="flex flex-col gap-3 p-6">
            <p className="serif-light text-[64px] leading-none tracking-[-0.02em]">Display</p>
            <p className="serif-light text-[32px]">
              Heading with one <em>italic</em> word
            </p>
            <p className="text-h2 font-medium">Section heading</p>
            <p className="text-body">Body text is fifteen pixels at regular weight.</p>
            <p className="tabular text-hero font-light">{formatINR(123456789)}</p>
            <p className="label-mono text-ink-3">Mono label</p>
          </div>
        </Card>
        <Card>
          <CardHeader label="Controls" />
          <div className="flex flex-wrap items-center gap-3 p-6">
            <Button variant="primary">Primary</Button>
            <Button>Secondary</Button>
            <Button variant="text">Text</Button>
            <Button variant="danger">Danger</Button>
            <Button disabled>Disabled</Button>
            <Chip selected>Selected</Chip>
            <Chip>Chip</Chip>
            <Badge tone="positive">On track</Badge>
            <Badge tone="attention">Attention</Badge>
            <Badge tone="negative">Over</Badge>
            <Badge tone="agent">Agent</Badge>
            <SourceBadge source="llm" confidence={0.62} />
            <SourceBadge source="rule" />
            <Stat label="Stat" value={formatINR(49950)} hint="Hint text" />
          </div>
        </Card>
        <div className="grid gap-5 lg:grid-cols-2">
          <Card className="p-6">
            <SkeletonBlock lines={4} />
          </Card>
          <Card className="p-6">
            <EmptyState message={copy.dashboard.reviewZero} />
          </Card>
          <Card className="p-6">
            <ErrorState
              code="TOOL_FAILURE"
              message="The bank did not respond."
              onRetry={() => undefined}
            />
          </Card>
          <Card className="p-6">
            <InsufficientDataState message={copy.dashboard.forecastMissing('–', '–')} />
          </Card>
        </div>
      </div>
    </Page>
  );
}
