export type PlanTier = 'Trial' | 'Starter' | 'Professional' | 'Enterprise';

export type SubscriptionPlan = {
  slug: string;
  name: string;
  tier: PlanTier;
  price: string;
  priceDetail?: string;
  tagline: string;
  dataSources: string;
  scanFrequency: string;
  features: string[];
  highlighted?: boolean;
};

export type ScanCategory = {
  slug: string;
  name: string;
  description: string;
  icon: string;
  checks: string[];
  integrations: string[];
};

export const PLANS: SubscriptionPlan[] = [
  {
    slug: 'starter',
    name: 'Starter',
    tier: 'Starter',
    price: '$500',
    priceDetail: '/month',
    tagline: 'For teams getting started with data quality.',
    dataSources: 'Up to 25',
    scanFrequency: 'Daily automated scans',
    features: [
      'Up to 25 data sources',
      'Daily automated scans',
      'Auto-fix generation',
      'Slack/email alerts',
      '5 team members',
      'Email support',
    ]
  },
  {
    slug: 'professional',
    name: 'Professional',
    tier: 'Professional',
    price: '$1,500',
    priceDetail: '/month',
    tagline: 'For growing data teams with complex pipelines.',
    dataSources: 'Up to 100',
    scanFrequency: 'Hourly + on-demand',
    highlighted: true,
    features: [
      'Up to 100 data sources',
      'Hourly automated scans',
      'Sandbox testing environment',
      'GitHub/GitLab PR integration',
      'Root cause analysis',
      'Unlimited team members',
      'Priority support',
    ]
  },
  {
    slug: 'enterprise',
    name: 'Enterprise',
    tier: 'Enterprise',
    price: 'Custom',
    priceDetail: 'starting at $5,000/mo',
    tagline: 'For large-scale data operations.',
    dataSources: 'Unlimited',
    scanFrequency: 'Real-time + scheduled',
    features: [
      'Unlimited data sources',
      'Real-time monitoring',
      'Custom rules engine',
      'SSO + role-based access control',
      'Dedicated support channel',
      'Quarterly business reviews',
      'API access for CI/CD',
      'SOC2 evidence packs',
    ]
  }
];

export const SCAN_CATEGORIES: ScanCategory[] = [
  {
    slug: 'data-freshness',
    name: 'Data Freshness',
    description: 'Track table-level freshness vs SLOs. Know when data is late before dashboards break.',
    icon: 'chart',
    checks: [
      'Table freshness vs expected SLO',
      'Row count anomaly detection',
      'Schema drift monitoring',
      'Null/duplicate percentage tracking',
      'Partition freshness validation',
    ],
    integrations: ['Snowflake', 'BigQuery', 'Redshift', 'dbt', 'Databricks']
  },
  {
    slug: 'pipeline-health',
    name: 'Pipeline Health',
    description: 'Job success rates, failure patterns, MTTR tracking. Catch issues before they cascade.',
    icon: 'activity',
    checks: [
      'Job success/failure rates',
      'Run duration anomalies',
      'Dependency chain health',
      'Alert noise analysis',
      'MTTR tracking',
    ],
    integrations: ['Airflow', 'Dagster', 'Prefect', 'dbt Cloud']
  },
  {
    slug: 'data-quality',
    name: 'Data Quality',
    description: 'Anomaly detection, schema validation, and data integrity checks across your stack.',
    icon: 'check',
    checks: [
      'Statistical anomaly detection',
      'Schema validation',
      'Null rate monitoring',
      'Duplicate detection',
      'Distribution drift',
    ],
    integrations: ['Snowflake', 'BigQuery', 'PostgreSQL', 'dbt']
  },
  {
    slug: 'database-performance',
    name: 'Database Performance',
    description: 'Query performance, schema drift, missing indexes. Keep your databases fast and reliable.',
    icon: 'database',
    checks: [
      'Slow query detection',
      'Missing index suggestions',
      'Schema change tracking',
      'Connection pool health',
      'Storage growth trends',
    ],
    integrations: ['PostgreSQL', 'MySQL', 'SQL Server', 'Snowflake']
  }
];

export type AddOn = {
  name: string;
  price: string;
  description: string;
};

export const ADD_ONS: AddOn[] = [
  {
    name: 'Implementation Support',
    price: '$2,500',
    description: 'White-glove onboarding with our team + custom integration setup'
  },
  {
    name: 'Additional Data Sources',
    price: '$50/source/mo',
    description: 'Add more data sources beyond your plan limit'
  },
  {
    name: 'Custom Integration',
    price: '$1,000/setup',
    description: 'Connect proprietary or unsupported data sources'
  },
  {
    name: 'Dedicated Support',
    price: '$1,500/mo',
    description: 'Private Slack channel + 2-hour response SLA'
  }
];

export const FOOTER_NOTES = [
  'All access is read-only. We never modify your systems or data.',
  'All plans include a 14-day free trial. No credit card required.',
  'Enterprise pricing based on data sources, users, and support requirements.',
  'SOC2 Type II certification available for Professional and Enterprise plans.'
];

// Helper functions
export function getAllPlans() {
  return PLANS;
}

export function getPlanBySlug(slug: string) {
  return PLANS.find(p => p.slug === slug) || null;
}

export function getAllCategories() {
  return SCAN_CATEGORIES;
}

export function getCategoryBySlug(slug: string) {
  return SCAN_CATEGORIES.find(c => c.slug === slug) || null;
}

export function getAddOns() {
  return ADD_ONS;
}

// Legacy exports for compatibility
export type ServicePackage = {
  slug: string;
  name: string;
  tier?: string;
  category: string;
  tagline: string;
  price: string;
  access: string;
  duration: string;
  checks: string[];
  prevents: string;
};

export const PACKAGES: ServicePackage[] = SCAN_CATEGORIES.map(cat => ({
  slug: cat.slug,
  name: cat.name,
  category: 'Scan',
  tagline: cat.description,
  price: 'Included in plan',
  access: cat.integrations.join(', '),
  duration: '~5-30 minutes',
  checks: cat.checks,
  prevents: cat.description,
}));

export function getAllPackages() {
  return PACKAGES;
}

export function getPackageBySlug(slug: string) {
  return PACKAGES.find(p => p.slug === slug) || null;
}

export function groupByCategory() {
  return {
    Data: PACKAGES.filter(p => ['data-freshness', 'pipeline-health', 'data-quality', 'database-performance'].includes(p.slug)),
    Code: [],
    Bundle: []
  } as const;
}
