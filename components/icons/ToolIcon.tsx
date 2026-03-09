'use client';

import React from 'react';
import { cn } from '@/lib/utils';

/**
 * Shared tool/integration icon component.
 * Renders brand SVG logos for known tools, falls back to a
 * coloured initial badge for unknown types.
 *
 * Usage:
 *   <ToolIcon toolType="bigquery" size={28} />
 *   <ToolIcon toolType="snowflake" size={20} className="flex-shrink-0" />
 *
 * To add a new integration:
 *   1. Add an SVG component function below
 *   2. Add entry to TOOL_SVGS registry
 *   3. Add entry to TOOL_LABELS
 */

export interface ToolIconProps {
  toolType: string;
  /** px, default 28 */
  size?: number;
  className?: string;
}

export function ToolIcon({ toolType, size = 28, className }: ToolIconProps) {
  const key = toolType.toLowerCase();
  const LogoSvg = TOOL_SVGS[key];
  const label = TOOL_LABELS[key] || toolType.replace(/_/g, ' ');

  if (LogoSvg) {
    return (
      <div
        className={cn('flex items-center justify-center flex-shrink-0 rounded-lg', className)}
        style={{ width: size, height: size }}
        role="img"
        aria-label={label}
        title={label}
      >
        <LogoSvg size={size} />
      </div>
    );
  }

  // Fallback: coloured initial
  const color = FALLBACK_COLORS[key] || '#6B7280';
  const initials = key.slice(0, 2).toUpperCase();
  const fontSize = Math.max(8, size * 0.32);

  return (
    <div
      className={cn('flex items-center justify-center flex-shrink-0 rounded-lg text-white font-bold', className)}
      style={{ width: size, height: size, backgroundColor: color, fontSize }}
      role="img"
      aria-label={label}
      title={label}
    >
      {initials}
    </div>
  );
}

/** Alias for new code — same component, clearer name. */
export { ToolIcon as IntegrationIcon };

/** All integration type keys that have SVG icons (populated at module load). */
export let INTEGRATION_TYPES: string[] = [];

// ─── Human-readable labels for accessibility ─────────────────
const TOOL_LABELS: Record<string, string> = {
  bigquery: 'BigQuery',
  snowflake: 'Snowflake',
  postgres: 'PostgreSQL',
  redshift: 'Amazon Redshift',
  databricks: 'Databricks',
  dbt_cloud: 'dbt Cloud',
  dbt_core: 'dbt Core',
  fivetran: 'Fivetran',
  airbyte: 'Airbyte',
  looker: 'Looker',
  tableau: 'Tableau',
  metabase: 'Metabase',
  powerbi: 'Power BI',
  airflow: 'Apache Airflow',
  dagster: 'Dagster',
  prefect: 'Prefect',
  slack: 'Slack',
  jira: 'Jira',
  linear: 'Linear',
  github: 'GitHub',
  github_issues: 'GitHub Issues',
  stitch: 'Stitch',
  sqlserver: 'SQL Server',
  azure_sql: 'Azure SQL',
  azure_synapse: 'Azure Synapse',
  mysql: 'MySQL',
  n8n: 'n8n',
  amazon_s3: 'Amazon S3',
  gcs: 'Google Cloud Storage',
  adls: 'Azure Data Lake Storage',
  monte_carlo: 'Monte Carlo',
  bigeye: 'Bigeye',
  soda: 'Soda',
  elementary: 'Elementary',
  pagerduty: 'PagerDuty',
  opsgenie: 'OpsGenie',
  teams: 'Microsoft Teams',
  asana: 'Asana',
  gitlab: 'GitLab',
  bitbucket: 'Bitbucket',
  linux_server: 'Linux Server',
  custom_webhook: 'Custom Webhook',
};

// ─── Fallback colours for future unknown tools ──────────────
const FALLBACK_COLORS: Record<string, string> = {};

// ─── SVG Logo Components ──────────────────────────────────────
// Brand-faithful simplified SVGs at native viewBox.
// Each accepts { size: number } and renders an <svg> at that size.

type SvgProps = { size: number };

function BigQueryLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6.214 17.759l-3.028 3.029A11.94 11.94 0 010 12C0 5.373 5.373 0 12 0c3.314 0 6.314 1.343 8.485 3.515l-3.03 3.03A7.17 7.17 0 0012 4.8 7.2 7.2 0 004.8 12c0 2.17.96 4.116 2.478 5.436l-1.064 .323z" fill="#4285F4"/>
      <path d="M12 19.2A7.2 7.2 0 0019.2 12c0-2.17-.96-4.116-2.478-5.436l3.793-3.079A11.94 11.94 0 0124 12c0 6.627-5.373 12-12 12a11.94 11.94 0 01-8.814-3.871l3.028-3.029A7.17 7.17 0 0012 19.2z" fill="#4285F4"/>
      <path d="M14.4 9.6v5.1l2.1 1.2-.3-1.2V9.6h-1.8z" fill="#4285F4"/>
      <path d="M9.6 10.8v3.9l2.1 1.2V10.8H9.6z" fill="#4285F4"/>
      <path d="M12.9 8.4v6.9l1.5.6V8.4h-1.5z" fill="#4285F4"/>
      <path d="M7.5 12.6v2.1l2.1 1.2v-3.3H7.5z" fill="#4285F4"/>
      <path d="M15.8 16.4l1.7 1 1.3-1.3-1.7-1-1.3 1.3z" fill="#4285F4"/>
    </svg>
  );
}

function SnowflakeLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2v20M2 12h20M4.93 4.93l14.14 14.14M19.07 4.93L4.93 19.07" stroke="#29B5E8" strokeWidth="2" strokeLinecap="round"/>
      <circle cx="12" cy="2" r="1.2" fill="#29B5E8"/>
      <circle cx="12" cy="22" r="1.2" fill="#29B5E8"/>
      <circle cx="2" cy="12" r="1.2" fill="#29B5E8"/>
      <circle cx="22" cy="12" r="1.2" fill="#29B5E8"/>
      <circle cx="4.93" cy="4.93" r="1.2" fill="#29B5E8"/>
      <circle cx="19.07" cy="19.07" r="1.2" fill="#29B5E8"/>
      <circle cx="19.07" cy="4.93" r="1.2" fill="#29B5E8"/>
      <circle cx="4.93" cy="19.07" r="1.2" fill="#29B5E8"/>
      <circle cx="12" cy="7" r="0.8" fill="#29B5E8"/>
      <circle cx="12" cy="17" r="0.8" fill="#29B5E8"/>
      <circle cx="7" cy="12" r="0.8" fill="#29B5E8"/>
      <circle cx="17" cy="12" r="0.8" fill="#29B5E8"/>
    </svg>
  );
}

function PostgresLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M17.128 1.998c-1.455-.053-2.782.353-3.891.94-.812-.227-1.678-.358-2.581-.33-1.44.044-2.72.52-3.742 1.283C5.762 4.78 5.04 6.188 4.8 7.97c-.24 1.782.097 3.87.89 6.094.55 1.547 1.27 2.782 2.05 3.576.39.397.82.696 1.27.847.225.075.455.108.68.098.37-.016.72-.163 1.01-.418.49.338 1.08.488 1.65.446.68-.05 1.32-.352 1.78-.888.14.008.28.003.42-.018.67-.1 1.25-.522 1.68-1.118.43-.596.72-1.368.85-2.23l.06-.39c.32-.037.62-.12.89-.255 1.01-.51 1.59-1.49 1.91-2.573.32-1.083.4-2.28.36-3.24-.04-.96-.19-1.658-.19-1.658l-.01-.047c-.26-1.36-.84-2.48-1.65-3.27-.81-.79-1.86-1.27-3.12-1.32z" fill="#336791"/>
      <path d="M16.934 3.29c.97.04 1.76.41 2.37 1.005.61.595 1.08 1.47 1.3 2.614 0 0 .14.657.18 1.576.04.919-.04 2.06-.34 3.06-.3 1-.81 1.79-1.59 2.18-.2.1-.42.17-.66.2l-.02.15c-.12.79-.38 1.48-.74 1.98-.36.5-.82.84-1.33.92-.08.01-.17.02-.25.01l-.01.08c-.5.88-1.24 1.32-1.99 1.37-.46.03-.92-.08-1.33-.33-.12.17-.27.31-.44.42-.27.18-.58.26-.89.23-.31-.03-.64-.17-.95-.44-.62-.54-1.22-1.57-1.72-2.97-.73-2.05-1.07-4.02-.85-5.64.22-1.62.87-2.86 1.93-3.64.88-.65 1.98-1.05 3.26-1.09.85-.027 1.66.08 2.42.29.62-.42 1.41-.68 2.28-.65l-.05-.02-.01.2.01-.2z" fill="#336791"/>
      <path d="M12.5 18.77c.53-.04 1.04-.35 1.39-.84.35-.49.58-1.15.68-1.9l.07-.52.18-.01c.16-.01.32-.06.47-.13.56-.28.97-.9 1.24-1.72.27-.81.35-1.83.32-2.7-.03-.87-.15-1.5-.15-1.5l-.01-.05c-.2-1.04-.66-1.82-1.22-2.36-.57-.54-1.23-.83-1.97-.86-.64-.02-1.22.14-1.73.42l-.12-.04c-.69-.2-1.42-.3-2.18-.28-1.12.03-2.1.37-2.87.94-.88.65-1.42 1.66-1.61 3.08-.2 1.42.1 3.27.8 5.23.47 1.32 1.03 2.27 1.55 2.72.26.23.49.33.68.36.19.03.37 0 .54-.1.17-.1.33-.27.46-.5l.13.07c.35.2.73.3 1.12.27l.02-.01.14.2z" fill="#fff" fillOpacity=".15"/>
    </svg>
  );
}

function RedshiftLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2L3 7v10l9 5 9-5V7l-9-5z" fill="#8C4FFF"/>
      <path d="M12 2L3 7l9 5 9-5-9-5z" fill="#B17FFF"/>
      <path d="M12 12v10l9-5V7l-9 5z" fill="#6B2FCC"/>
      <path d="M12 12L3 7v10l9 5V12z" fill="#8C4FFF"/>
      <path d="M8 9.5l4 2.2 4-2.2" stroke="#fff" strokeWidth="0.8" strokeLinecap="round" fill="none"/>
      <path d="M12 11.7V16" stroke="#fff" strokeWidth="0.8" strokeLinecap="round"/>
    </svg>
  );
}

function DbtLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12.56 3.06c-.3-.3-.78-.3-1.08 0L3.06 11.5c-.3.3-.3.78 0 1.08l8.42 8.42c.3.3.78.3 1.08 0l8.42-8.42c.3-.3.3-.78 0-1.08l-8.42-8.42z" fill="#FF694A"/>
      <path d="M13.5 8.5v3h3v1.5h-3v3H12v-3H9V11.5h3v-3h1.5z" fill="#fff"/>
    </svg>
  );
}

function FivetranLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#0073FF"/>
      <path d="M8.5 7h7L14 10h-4l-1.5 3H13l-1.5 4H8l1.5-4H7l1.5-3h2.5L12.5 7" fill="#fff" fillOpacity=".9"/>
    </svg>
  );
}

function AirbyteLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#615EFF"/>
      <path d="M7.5 12.5l3.5 3.5 6-7" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M7.5 9l3.5 3.5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" opacity=".5"/>
    </svg>
  );
}

function LookerLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#34A853"/>
      <circle cx="12" cy="11" r="3" stroke="#fff" strokeWidth="1.5" fill="none"/>
      <path d="M14.5 13.5L17 16" stroke="#fff" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function TableauLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12.5 2.5v4h4v1h-4v4h-1v-4h-4v-1h4v-4h1z" fill="#E8762D"/>
      <path d="M19.5 6v3h3v1h-3v3h-1v-3h-3V9h3V6h1z" fill="#C72037"/>
      <path d="M5.5 6v3h3v1h-3v3h-1v-3H1.5V9h3V6h1z" fill="#5B879B"/>
      <path d="M12.5 12.5v4h4v1h-4v4h-1v-4h-4v-1h4v-4h1z" fill="#5B879B"/>
      <path d="M19.5 14.5v2.5h2.5v.5h-2.5v2.5h-.5v-2.5h-2.5v-.5h2.5v-2.5h.5z" fill="#E8762D"/>
      <path d="M5.5 14.5v2.5H3v.5h2.5v2.5h.5v-2.5H8.5v-.5H6v-2.5h-.5z" fill="#C72037"/>
    </svg>
  );
}

function MetabaseLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#509EE3"/>
      <circle cx="8.5" cy="10" r="1.5" fill="#fff"/>
      <circle cx="15.5" cy="10" r="1.5" fill="#fff"/>
      <path d="M8.5 15c0 0 1.5 2 3.5 2s3.5-2 3.5-2" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" fill="none"/>
    </svg>
  );
}

function AirflowLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 4L4 12l8 8 8-8-8-8z" fill="#017CEE"/>
      <path d="M12 4l8 8-8 8" fill="#00AD46"/>
      <path d="M12 4L4 12l8 8" fill="#04D659"/>
      <path d="M12 8l-4 4 4 4 4-4-4-4z" fill="#fff" fillOpacity=".3"/>
      <circle cx="12" cy="12" r="1.5" fill="#fff"/>
    </svg>
  );
}

function DagsterLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2L3 7.5v9L12 22l9-5.5v-9L12 2z" fill="#4F43DD"/>
      <path d="M12 8l-4.5 2.5v5L12 18l4.5-2.5v-5L12 8z" fill="#fff" fillOpacity=".25"/>
      <circle cx="12" cy="12" r="2" fill="#fff"/>
    </svg>
  );
}

function PrefectLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#0052FF"/>
      <path d="M8 12l3 3 5-6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function DatabricksLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 1L2 6.5 12 12l10-5.5L12 1z" fill="#FF3621"/>
      <path d="M2 12l10 5.5L22 12" stroke="#FF3621" strokeWidth="1.5" fill="none"/>
      <path d="M2 17l10 5.5L22 17" stroke="#FF3621" strokeWidth="1.5" fill="none"/>
      <path d="M2 6.5v5.5l10 5.5V12L2 6.5z" fill="#FF3621" fillOpacity=".3"/>
      <path d="M22 6.5v5.5l-10 5.5V12l10-5.5z" fill="#FF3621" fillOpacity=".15"/>
    </svg>
  );
}

function PowerBILogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="2" fill="#F2C811"/>
      <rect x="7" y="10" width="2.5" height="6" rx="0.5" fill="#fff"/>
      <rect x="10.75" y="7" width="2.5" height="9" rx="0.5" fill="#fff"/>
      <rect x="14.5" y="9" width="2.5" height="7" rx="0.5" fill="#fff"/>
    </svg>
  );
}

function SlackLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M5.042 15.166a2.083 2.083 0 11-2.084-2.083h2.084v2.083z" fill="#E01E5A"/>
      <path d="M6.125 15.166a2.083 2.083 0 014.167 0v5.209a2.083 2.083 0 11-4.167 0v-5.209z" fill="#E01E5A"/>
      <path d="M8.875 5.042a2.083 2.083 0 112.083-2.084v2.084H8.875z" fill="#36C5F0"/>
      <path d="M8.875 6.125a2.083 2.083 0 010 4.167H3.667a2.083 2.083 0 010-4.167h5.208z" fill="#36C5F0"/>
      <path d="M18.958 8.875a2.083 2.083 0 112.084 2.083h-2.084V8.875z" fill="#2EB67D"/>
      <path d="M17.875 8.875a2.083 2.083 0 01-4.167 0V3.667a2.083 2.083 0 014.167 0v5.208z" fill="#2EB67D"/>
      <path d="M15.125 18.958a2.083 2.083 0 11-2.083 2.084v-2.084h2.083z" fill="#ECB22E"/>
      <path d="M15.125 17.875a2.083 2.083 0 010-4.167h5.208a2.083 2.083 0 010 4.167h-5.208z" fill="#ECB22E"/>
    </svg>
  );
}

function JiraLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M22.16 11.1L13.3 2.24 12 .94 4.7 8.24l-2.86 2.86a.96.96 0 000 1.36l6.62 6.62L12 22.54l7.3-7.3.22-.22 2.64-2.56a.96.96 0 000-1.36zM12 15.36L8.64 12 12 8.64 15.36 12 12 15.36z" fill="#2684FF"/>
      <path d="M12 8.64A4.7 4.7 0 017.07 3.8L1.84 9.02l6.62 6.62L12 12.18V8.64z" fill="url(#jira_a)"/>
      <path d="M15.38 11.98L12 15.36a4.7 4.7 0 010 6.64l5.28-5.28-2.9-4.74z" fill="url(#jira_b)"/>
      <defs>
        <linearGradient id="jira_a" x1="11.15" y1="5.44" x2="5.16" y2="9.82" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0052CC"/><stop offset="1" stopColor="#2684FF"/>
        </linearGradient>
        <linearGradient id="jira_b" x1="12.9" y1="18.63" x2="18.86" y2="14.27" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0052CC"/><stop offset="1" stopColor="#2684FF"/>
        </linearGradient>
      </defs>
    </svg>
  );
}

function LinearLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3.357 14.036a9.998 9.998 0 006.607 6.607L3.357 14.036z" fill="#5E6AD2"/>
      <path d="M2.05 11.293a10.012 10.012 0 002.184 7.48L2.05 11.293z" fill="#5E6AD2"/>
      <path d="M2 10c0-.34.017-.675.05-1.005l12.955 12.955A10.002 10.002 0 012 10z" fill="#5E6AD2"/>
      <path d="M3.69 5.227L18.773 20.31A10 10 0 003.69 5.227z" fill="#5E6AD2"/>
      <path d="M5.95 3.297l14.753 14.753a10 10 0 00-14.752-14.753z" fill="#5E6AD2"/>
      <path d="M9.964 2.05L21.95 14.036A10 10 0 009.965 2.05z" fill="#5E6AD2"/>
      <path d="M14.036 3.357L20.643 9.964A10 10 0 0014.036 3.357z" fill="#5E6AD2"/>
    </svg>
  );
}

function GithubLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.865 8.166 6.839 9.489.5.092.682-.217.682-.482 0-.237-.009-.866-.013-1.7-2.782.604-3.369-1.34-3.369-1.34-.454-1.156-1.11-1.463-1.11-1.463-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03.892 1.529 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 .84-.269 2.75 1.025A9.578 9.578 0 0112 6.836c.85.004 1.705.114 2.504.336 1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.203 2.394.1 2.647.64.699 1.028 1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 0 1.336-.012 2.415-.012 2.743 0 .267.18.578.688.48C19.138 20.163 22 16.418 22 12c0-5.523-4.477-10-10-10z" fill="currentColor"/>
    </svg>
  );
}

function StitchLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#59C29A"/>
      <path d="M7 10l3 3-3 3" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M13 16h4" stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  );
}

// ─── New SVG Logo Components ──────────────────────────────────

function SqlServerLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="12" cy="6.5" rx="7" ry="3" fill="#CC2927"/>
      <path d="M5 6.5v11c0 1.66 3.13 3 7 3s7-1.34 7-3v-11" stroke="#CC2927" strokeWidth="1.2" fill="none"/>
      <path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3" stroke="#CC2927" strokeWidth="1" fill="none" opacity=".5"/>
      <path d="M5 17c0 1.66 3.13 3 7 3s7-1.34 7-3" stroke="#fff" strokeWidth="0.6" fill="none" opacity=".3"/>
    </svg>
  );
}

function AzureSqlLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2l8 4.5v11L12 22l-8-4.5v-11L12 2z" fill="#0078D4"/>
      <ellipse cx="12" cy="10" rx="4" ry="1.8" fill="#fff" fillOpacity=".3"/>
      <path d="M8 10v4.5c0 1 1.79 1.8 4 1.8s4-.8 4-1.8V10" stroke="#fff" strokeWidth="0.8" fill="none"/>
      <ellipse cx="12" cy="10" rx="4" ry="1.8" stroke="#fff" strokeWidth="0.8" fill="none"/>
    </svg>
  );
}

function AzureSynapseLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2l8 4.5v11L12 22l-8-4.5v-11L12 2z" fill="#0078D4"/>
      <circle cx="12" cy="12" r="3" stroke="#fff" strokeWidth="1" fill="none"/>
      <circle cx="12" cy="12" r="1" fill="#fff"/>
      <path d="M12 5v4M12 15v4M5.5 8.5l3.5 2M15 13.5l3.5 2M5.5 15.5l3.5-2M15 10.5l3.5-2" stroke="#fff" strokeWidth="0.8" strokeLinecap="round" opacity=".6"/>
    </svg>
  );
}

function MySqlLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <ellipse cx="12" cy="6.5" rx="7" ry="3" fill="#4479A1"/>
      <path d="M5 6.5v11c0 1.66 3.13 3 7 3s7-1.34 7-3v-11" stroke="#4479A1" strokeWidth="1.2" fill="none"/>
      <path d="M5 12c0 1.66 3.13 3 7 3s7-1.34 7-3" stroke="#4479A1" strokeWidth="1" fill="none" opacity=".5"/>
      <path d="M19 6.5c0 1.66-3.13 3-7 3s-7-1.34-7-3" stroke="#fff" strokeWidth="0.6" fill="none" opacity=".3"/>
      <path d="M10 11v4l2-2 2 2v-4" stroke="#fff" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" opacity=".7"/>
    </svg>
  );
}

function N8nLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2" y="2" width="20" height="20" rx="4" fill="#EA4B71"/>
      <circle cx="7" cy="12" r="2" fill="#fff"/>
      <circle cx="17" cy="8" r="2" fill="#fff"/>
      <circle cx="17" cy="16" r="2" fill="#fff"/>
      <path d="M9 11.5l6-2.5M9 12.5l6 2.5" stroke="#fff" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  );
}

function AmazonS3Logo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h16v10a2 2 0 01-2 2H6a2 2 0 01-2-2V7z" fill="#FF9900"/>
      <path d="M4 7l2-3h12l2 3" stroke="#FF9900" strokeWidth="1.5" fill="#FFBD59"/>
      <path d="M12 10v5M9.5 12.5h5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}

function GcsLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 7h16v10a2 2 0 01-2 2H6a2 2 0 01-2-2V7z" fill="#4285F4"/>
      <path d="M4 7l2-3h12l2 3" stroke="#4285F4" strokeWidth="1.5" fill="#5E97F6"/>
      <circle cx="12" cy="12.5" r="2.5" stroke="#fff" strokeWidth="1.2" fill="none"/>
      <path d="M12 10v2.5h2.5" stroke="#fff" strokeWidth="1" strokeLinecap="round"/>
    </svg>
  );
}

function AdlsLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2l8 4.5v11L12 22l-8-4.5v-11L12 2z" fill="#0078D4"/>
      <path d="M7 14c1.5-2 3-4 5-4s3.5 2 5 4" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" fill="none"/>
      <path d="M7 14c0 1 2.24 2 5 2s5-1 5-2" stroke="#fff" strokeWidth="0.8" fill="none" opacity=".6"/>
      <circle cx="12" cy="9" r="1" fill="#fff" opacity=".7"/>
    </svg>
  );
}

function MonteCarloLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#00D4AA"/>
      <path d="M12 6l5 3v6l-5 3-5-3V9l5-3z" stroke="#fff" strokeWidth="1.2" fill="none"/>
      <path d="M9 13l2 2 4-4" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function BigeyeLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#FF6B35"/>
      <path d="M4.5 12s3-5 7.5-5 7.5 5 7.5 5-3 5-7.5 5-7.5-5-7.5-5z" stroke="#fff" strokeWidth="1.2" fill="none"/>
      <circle cx="12" cy="12" r="2.5" fill="#fff"/>
      <circle cx="12" cy="12" r="1" fill="#FF6B35"/>
    </svg>
  );
}

function SodaLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#00C7B7"/>
      <path d="M8 12.5l2.5-4h3l2.5 4-2.5 4h-3l-2.5-4z" stroke="#fff" strokeWidth="1.2" fill="none"/>
      <path d="M10 12l1.5 1.5 3-3" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function ElementaryLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#FF914D"/>
      <path d="M9 8h6M9 12h5M9 16h4" stroke="#fff" strokeWidth="1.8" strokeLinecap="round"/>
    </svg>
  );
}

function PagerDutyLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="3" fill="#06AC38"/>
      <path d="M9 7h3.5a3.5 3.5 0 010 7H11v3H9V7z" fill="#fff"/>
      <path d="M11 9v3h1.5a1.5 1.5 0 000-3H11z" fill="#06AC38"/>
    </svg>
  );
}

function OpsgenieLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#2684FF"/>
      <path d="M12 5v8" stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
      <path d="M8 8l4 5 4-5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity=".5"/>
      <circle cx="12" cy="17" r="1.5" fill="#fff"/>
    </svg>
  );
}

function TeamsLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="3" width="18" height="18" rx="3" fill="#6264A7"/>
      <path d="M8 9h8M12 9v7" stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
      <circle cx="17.5" cy="8" r="2" fill="#7B83EB"/>
      <path d="M16 11h3a2 2 0 012 2v2h-5v-4z" fill="#7B83EB"/>
    </svg>
  );
}

function AsanaLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="7" r="3.5" fill="#F06A6A"/>
      <circle cx="6" cy="15.5" r="3.5" fill="#F06A6A"/>
      <circle cx="18" cy="15.5" r="3.5" fill="#F06A6A"/>
    </svg>
  );
}

function GitlabLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 20.9L16.2 8.3H7.8L12 20.9z" fill="#E24329"/>
      <path d="M12 20.9L7.8 8.3H2.6L12 20.9z" fill="#FC6D26"/>
      <path d="M2.6 8.3L1.1 12.9c-.14.42 0 .88.35 1.13L12 20.9 2.6 8.3z" fill="#FCA326"/>
      <path d="M2.6 8.3h5.2L5.6 2.4c-.14-.43-.75-.43-.89 0L2.6 8.3z" fill="#E24329"/>
      <path d="M12 20.9l4.2-12.6h5.2L12 20.9z" fill="#FC6D26"/>
      <path d="M21.4 8.3l1.5 4.6c.14.42 0 .88-.35 1.13L12 20.9l9.4-12.6z" fill="#FCA326"/>
      <path d="M21.4 8.3h-5.2l2.1-5.9c.14-.43.75-.43.89 0l2.2 5.9z" fill="#E24329"/>
    </svg>
  );
}

function BitbucketLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3.27 4.28a.83.83 0 00-.82.96l2.72 16.53a1.13 1.13 0 001.1.93h11.63a.83.83 0 00.82-.69l2.73-16.77a.83.83 0 00-.82-.96H3.27z" fill="#2684FF"/>
      <path d="M14.68 14.72H9.38l-1.37-7.44h8.06l-1.39 7.44z" fill="url(#bb_a)"/>
      <defs>
        <linearGradient id="bb_a" x1="17.36" y1="8.58" x2="8.87" y2="16.72" gradientUnits="userSpaceOnUse">
          <stop stopColor="#0052CC"/><stop offset="1" stopColor="#2684FF"/>
        </linearGradient>
      </defs>
    </svg>
  );
}

function LinuxServerLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="5" y="3" width="14" height="14" rx="2" fill="#333"/>
      <rect x="7" y="5" width="10" height="8" rx="1" fill="#1a1a1a" stroke="#4AF626" strokeWidth="0.5"/>
      <path d="M8 8h3M8 10h5" stroke="#4AF626" strokeWidth="0.8" strokeLinecap="round"/>
      <rect x="8" y="19" width="8" height="2" rx="0.5" fill="#666"/>
      <path d="M10 17v2M14 17v2" stroke="#666" strokeWidth="1.2"/>
    </svg>
  );
}

function CustomWebhookLogo({ size }: SvgProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 2C6.477 2 2 6.477 2 12s4.477 10 10 10 10-4.477 10-10S17.523 2 12 2z" fill="#6B7280"/>
      <path d="M8 10c0-2.2 1.8-4 4-4s4 1.8 4 4" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" fill="none"/>
      <path d="M12 10v5" stroke="#fff" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M9 15h6" stroke="#fff" strokeWidth="1.5" strokeLinecap="round"/>
      <path d="M10 15l-2 3M14 15l2 3" stroke="#fff" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  );
}

// ─── Registry ─────────────────────────────────────────────────
const TOOL_SVGS: Record<string, (props: SvgProps) => React.ReactElement> = {
  // Warehouses
  bigquery: BigQueryLogo,
  snowflake: SnowflakeLogo,
  postgres: PostgresLogo,
  redshift: RedshiftLogo,
  databricks: DatabricksLogo,
  sqlserver: SqlServerLogo,
  azure_sql: AzureSqlLogo,
  azure_synapse: AzureSynapseLogo,
  mysql: MySqlLogo,
  // Ingestion
  fivetran: FivetranLogo,
  airbyte: AirbyteLogo,
  stitch: StitchLogo,
  // Transformation / Orchestration
  dbt_cloud: DbtLogo,
  dbt_core: DbtLogo,
  airflow: AirflowLogo,
  dagster: DagsterLogo,
  prefect: PrefectLogo,
  n8n: N8nLogo,
  // Reporting / BI
  looker: LookerLogo,
  tableau: TableauLogo,
  metabase: MetabaseLogo,
  powerbi: PowerBILogo,
  // Observability
  monte_carlo: MonteCarloLogo,
  bigeye: BigeyeLogo,
  soda: SodaLogo,
  elementary: ElementaryLogo,
  // Cloud Storage
  amazon_s3: AmazonS3Logo,
  gcs: GcsLogo,
  adls: AdlsLogo,
  // Version Control
  github: GithubLogo,
  github_issues: GithubLogo,
  gitlab: GitlabLogo,
  bitbucket: BitbucketLogo,
  // Notifications
  slack: SlackLogo,
  pagerduty: PagerDutyLogo,
  opsgenie: OpsgenieLogo,
  teams: TeamsLogo,
  // Project Management
  jira: JiraLogo,
  linear: LinearLogo,
  asana: AsanaLogo,
  // Infrastructure
  linux_server: LinuxServerLogo,
  // Other
  custom_webhook: CustomWebhookLogo,
};

// Populate the exported list now that TOOL_SVGS is defined.
INTEGRATION_TYPES = Object.keys(TOOL_SVGS);
