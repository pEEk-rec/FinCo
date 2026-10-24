/**
 * Copy for the cinematic landing page.
 * Honesty rules: no statistics, no fake user counts, no testimonials, no ratings.
 * Any illustrative figures are tagged as examples with figures-ok comments.
 */

export const landingCopy = {
  hero: {
    titleMain: 'Every rupee,',
    titleAccent: 'understood.',
    line: 'A calm ledger for living expenses.',
    ctaPrimary: 'Open the dashboard',
    points: ['Read-only bank statements', 'Zero automated transfers', 'On-device first'],
  },
  transformation: {
    badge: 'THE TRANSFORMATION',
    title: 'From scattered chaos to crystal clarity.',
    description:
      'Money arrives as noise: dozens of UPI transfers a week, half of them mysterious. Watch how FinCo brings order to the storm.',
    stages: [
      {
        id: 'scattered',
        label: 'Scattered',
        headline: 'Loose transactions in the wind.',
        body: 'Dozens of payments every week. Raw merchant codes, unfamiliar UPI IDs, and fading memories of what was spent where.',
      },
      {
        id: 'sorted',
        label: 'Sorted',
        headline: 'Automatically categorised by rules and context.',
        body: 'Food, rent, travel, and bills cluster effortlessly into dedicated channels, without manual spreadsheet sorting.',
      },
      {
        id: 'understood',
        label: 'Understood',
        headline: 'It asks at the moment you pay. Never in bulk.',
        body: 'When a transaction is ambiguous, FinCo presents one quiet prompt with smart guesses while your memory is fresh.',
      },
    ],
    interactivePrompt: {
      tag: 'Example',
      merchant: 'Ramesh K.',
      query: 'What was this payment for?',
      guesses: ['Chai & snacks', 'Stationery & prints', 'Shared auto split'],
      confirmedText: 'Assigned to Food · Undo anytime',
    },
  },
  statement: {
    badge: 'HOW IT WORKS',
    headline: 'It asks at the moment you pay. Never in bulk.',
    paragraph:
      'No weekend bookkeeping sessions. No deciphering cryptic SMS alerts weeks later. When a payment requires context, FinCo asks right away and remembers your intent.',
  },
  capabilities: {
    badge: 'CORE CAPABILITIES',
    title: 'Designed for transparency, built for quiet peace of mind.',
    cards: [
      {
        id: 'unsure',
        title: 'Asks only when unsure',
        description:
          'Recognises recurring routines and merchants automatically. Only queries you when confidence is below your threshold.',
        tag: 'Example',
      },
      {
        id: 'work',
        title: 'Clear evidence',
        description:
          'Every categorisation links directly to its source: merchant name, past history, or deterministic rules.',
        tag: 'Example',
      },
      {
        id: 'coming',
        title: 'Sees what is coming',
        description:
          'Tracks monthly velocity with high, expected, and low trajectories alongside upcoming fixed commitments.',
        tag: 'Example',
      },
      {
        id: 'goals',
        title: 'Your goals, your pace',
        description:
          'Visualises savings momentum without shaming or unrealistic restrictions. Adapts as your priorities shift.',
        tag: 'Example',
      },
      {
        id: 'learns',
        title: 'Learns what helps you',
        description:
          'Discovers trends in your discretionary spending and offers quiet comparisons against comparable weeks.',
        tag: 'Example',
      },
      {
        id: 'money',
        title: 'Never moves your money',
        description:
          'Zero execution privileges. There is no payment, transfer or trading feature, by design. You retain absolute control.',
        tag: 'Verified safeguard',
      },
    ],
  },
  principles: {
    badge: 'OUR PROMISE',
    title: 'Principles over hype',
    items: [
      {
        label: 'Private',
        title: 'Stays on your device',
        body: 'Your statement tokens and logs remain local. No selling to advertising networks or third-party brokers.',
      },
      {
        label: 'Explained',
        title: 'Every figure traceable',
        body: 'No mysterious algorithmic guesses. Every number, chart, and projection can be inspected to its raw source.',
      },
      {
        label: 'Yours',
        title: 'Nothing changes without you',
        body: 'No automatic reclassifications or surprise adjustments. The system proposes, and you decide.',
      },
      {
        label: 'Honest',
        title: 'Admits when data is sparse',
        body: 'When there is insufficient history, FinCo says "not enough data" instead of inventing synthetic projections.',
      },
    ],
  },
  finale: {
    badge: 'START WITH ONE PAYMENT',
    headline: 'See your month, clearly.',
    subhead:
      'A calm, honest ledger engineered for everyday living expenses. Free from ads, notifications spam, and hidden agendas.',
    cta: 'Open the dashboard',
    secondaryCta: 'Explore design tokens',
  },
  footer: {
    tagline: 'A calm ledger for living expenses.',
    statement:
      'FinCo is an open, private financial companion. It reads your statements to give you clarity and never handles transfers or funds.',
    links: [
      { label: 'Dashboard', href: '/' },
      { label: 'Review queue', href: '/review' },
      { label: 'Import data', href: '/connect' },
      { label: 'Design system', href: '/design' },
    ],
  },
} as const;
