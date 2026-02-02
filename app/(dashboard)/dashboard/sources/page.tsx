'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { 
  Database, Warehouse, BarChart3, RefreshCw, GitBranch,
  CheckCircle, AlertCircle, XCircle, Clock, Plus,
  Play, Search, Filter, ChevronRight, Settings,
  Upload, Network, FileJson, Loader2, Eye, Trash2
} from 'lucide-react';

// Pipeline Node from API
interface PipelineNode {
  id: string;
  name: string;
  layer: 'INGESTION' | 'TRANSFORMATION' | 'WAREHOUSE' | 'REPORTING';
  toolType: string;
  status: 'PENDING' | 'TESTING' | 'CONNECTED' | 'HEALTHY' | 'WARNING' | 'ERROR' | 'FAILED';
  config?: any;
  healthScore?: number;
  findingsCount: number;
  criticalCount: number;
  highCount: number;
  lastScanAt?: string;
  lastTestedAt?: string;
  stackId: string;
  stackName: string;
}

interface TableInfo {
  name: string;
  schema?: string;
  rowCount?: number;
  lastUpdated?: string;
}

interface LineageSnapshot {
  id: string;
  source: string;
  dialect: string;
  status: string;
  nodeCount: number;
  edgeCount: number;
  rootCount: number;
  leafCount: number;
  errorMessage?: string;
  createdAt: string;
  updatedAt: string;
}

// Tool display configuration
const TOOL_CONFIG: Record<string, { icon: any; color: string; label: string }> = {
  snowflake: { icon: Database, color: '#29B5E8', label: 'Snowflake' },
  bigquery: { icon: Database, color: '#4285F4', label: 'BigQuery' },
  redshift: { icon: Database, color: '#8C4FFF', label: 'Redshift' },
  postgres: { icon: Database, color: '#336791', label: 'PostgreSQL' },
  sqlserver: { icon: Database, color: '#CC2927', label: 'SQL Server' },
  azure_sql: { icon: Database, color: '#0078D4', label: 'Azure SQL' },
  fivetran: { icon: RefreshCw, color: '#0073FF', label: 'Fivetran' },
  airbyte: { icon: RefreshCw, color: '#615EFF', label: 'Airbyte' },
  stitch: { icon: RefreshCw, color: '#FFCB47', label: 'Stitch' },
  dbt_cloud: { icon: GitBranch, color: '#FF694A', label: 'dbt Cloud' },
  dbt_core: { icon: GitBranch, color: '#FF694A', label: 'dbt Core' },
  airflow: { icon: GitBranch, color: '#017CEE', label: 'Airflow' },
  dagster: { icon: GitBranch, color: '#4F43DD', label: 'Dagster' },
  looker: { icon: BarChart3, color: '#4285F4', label: 'Looker' },
  tableau: { icon: BarChart3, color: '#E97627', label: 'Tableau' },
  powerbi: { icon: BarChart3, color: '#F2C811', label: 'Power BI' },
  metabase: { icon: BarChart3, color: '#509EE3', label: 'Metabase' },
};

const LAYER_CONFIG = {
  INGESTION: { label: 'Ingestion', color: 'from-blue-500/20 to-blue-600/20', border: 'border-blue-500/30' },
  TRANSFORMATION: { label: 'Transformation', color: 'from-orange-500/20 to-orange-600/20', border: 'border-orange-500/30' },
  WAREHOUSE: { label: 'Warehouse', color: 'from-purple-500/20 to-purple-600/20', border: 'border-purple-500/30' },
  REPORTING: { label: 'Reporting', color: 'from-green-500/20 to-green-600/20', border: 'border-green-500/30' },
};

const STATUS_CONFIG = {
  CONNECTED: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  HEALTHY: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  WARNING: { icon: AlertCircle, color: 'text-yellow-400', bg: 'bg-yellow-500/10' },
  ERROR: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10' },
  FAILED: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10' },
  PENDING: { icon: Clock, color: 'text-gray-400', bg: 'bg-gray-500/10' },
  TESTING: { icon: RefreshCw, color: 'text-blue-400', bg: 'bg-blue-500/10' },
};

export default function DataSourcesPage() {
  const router = useRouter();
  const [nodes, setNodes] = useState<PipelineNode[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<PipelineNode | null>(null);
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());
  const [scanModalOpen, setScanModalOpen] = useState(false);
  const [scanRunning, setScanRunning] = useState(false);
  const [scanProgress, setScanProgress] = useState<{ type: string; status: string }[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [layerFilter, setLayerFilter] = useState<string | null>(null);
  
  // Lineage state
  const [lineageInfo, setLineageInfo] = useState<{ hasLineage: boolean; latest?: LineageSnapshot; history?: LineageSnapshot[] } | null>(null);
  const [lineageLoading, setLineageLoading] = useState(false);
  const [uploadingManifest, setUploadingManifest] = useState(false);
  const [lineageModalOpen, setLineageModalOpen] = useState(false);
  const [buildingFromWarehouse, setBuildingFromWarehouse] = useState(false);
  const [buildLineageProgress, setBuildLineageProgress] = useState<string | null>(null);
  
  // All discovered tables/datasets state
  const [allTables, setAllTables] = useState<{ table: string; dataset: string; nodeType: string; source: string }[]>([]);
  const [allTablesLoading, setAllTablesLoading] = useState(false);
  const [showAllTables, setShowAllTables] = useState(false);
  const [tableSearchQuery, setTableSearchQuery] = useState('');

  // Fetch pipeline nodes
  useEffect(() => {
    async function fetchNodes() {
      try {
        const response = await fetch('/api/pipeline/nodes');
        if (response.ok) {
          const data = await response.json();
          setNodes(data.nodes || []);
          
          // Auto-select first warehouse node if available
          const warehouseNodes = (data.nodes || []).filter((n: PipelineNode) => 
            n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')
          );
          if (warehouseNodes.length > 0) {
            setSelectedNode(warehouseNodes[0]);
          }
        }
      } catch (err) {
        console.error('Failed to fetch pipeline nodes:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchNodes();
  }, []);

  // Fetch lineage info and all tables
  useEffect(() => {
    async function fetchLineageInfo() {
      setLineageLoading(true);
      setAllTablesLoading(true);
      try {
        const response = await fetch('/api/lineage/manifest');
        if (response.ok) {
          const data = await response.json();
          setLineageInfo(data);
          
          // Extract tables from lineage nodes
          if (data.nodes && Array.isArray(data.nodes)) {
            const tablesList = data.nodes.map((node: any) => ({
              table: node.name || node.tableName || `${node.schema}.${node.tableName}`,
              dataset: node.schema || node.database || 'unknown',
              nodeType: node.nodeType || 'TABLE',
              source: 'lineage',
            }));
            setAllTables(tablesList);
          }
        }
      } catch (err) {
        console.error('Failed to fetch lineage info:', err);
      } finally {
        setLineageLoading(false);
        setAllTablesLoading(false);
      }
    }
    fetchLineageInfo();
  }, []);

  // Handle manifest upload
  const handleManifestUpload = async (file: File) => {
    setUploadingManifest(true);
    try {
      const formData = new FormData();
      formData.append('manifest', file);

      const response = await fetch('/api/lineage/manifest', {
        method: 'POST',
        body: formData,
      });

      if (response.ok) {
        const result = await response.json();
        // Refresh lineage info
        const infoResponse = await fetch('/api/lineage/manifest');
        if (infoResponse.ok) {
          const data = await infoResponse.json();
          setLineageInfo(data);
        }
        setLineageModalOpen(false);
        alert(`✅ Lineage built! ${result.message}`);
      } else {
        const error = await response.json();
        alert(`❌ Failed to upload manifest: ${error.error}`);
      }
    } catch (err) {
      console.error('Failed to upload manifest:', err);
      alert('❌ Failed to upload manifest. Make sure the scanner is running.');
    } finally {
      setUploadingManifest(false);
    }
  };

  // Handle lineage removal
  const handleRemoveLineage = async () => {
    if (!confirm('Are you sure you want to remove all lineage data? This will delete all nodes, edges, and snapshots.')) {
      return;
    }
    
    try {
      const response = await fetch('/api/lineage/manifest', {
        method: 'DELETE',
      });

      if (response.ok) {
        const result = await response.json();
        setLineageInfo({ hasLineage: false, latest: undefined, history: [] });
        alert(`✅ Lineage removed! ${result.message}`);
      } else {
        const error = await response.json();
        alert(`❌ Failed to remove lineage: ${error.error}`);
      }
    } catch (err) {
      console.error('Failed to remove lineage:', err);
      alert('❌ Failed to remove lineage.');
    }
  };

  // Build lineage from warehouse query history
  const handleBuildFromWarehouse = async () => {
    // Get the first connected warehouse node (for display purposes)
    const warehouseNode = nodes.find(n => 
      n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')
    );
    
    if (!warehouseNode) {
      alert('No connected warehouse found. Please connect a warehouse first.');
      return;
    }
    
    setBuildingFromWarehouse(true);
    setBuildLineageProgress('Analyzing query history...');
    
    try {
      // Don't pass integrationId - let the API find the warehouse automatically
      // The API will find any active warehouse integration (BIGQUERY, SNOWFLAKE, etc.)
      const response = await fetch('/api/lineage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          daysBack: 30,
        }),
      });

      if (response.ok) {
        const result = await response.json();
        setBuildLineageProgress('Building lineage graph...');
        
        // Refresh lineage info
        const infoResponse = await fetch('/api/lineage/manifest');
        if (infoResponse.ok) {
          const data = await infoResponse.json();
          setLineageInfo(data);
        }
        
        setLineageModalOpen(false);
        alert(`✅ Lineage built from ${warehouseNode.name}! Found ${result.stats?.nodesCreated || 0} tables and ${result.stats?.edgesCreated || 0} relationships.`);
      } else {
        const error = await response.json();
        alert(`❌ Failed to build lineage: ${error.error}`);
      }
    } catch (err) {
      console.error('Failed to build lineage from warehouse:', err);
      alert('❌ Failed to build lineage. Make sure the scanner backend is running.');
    } finally {
      setBuildingFromWarehouse(false);
      setBuildLineageProgress(null);
    }
  };

  // Fetch tables when a warehouse node is selected
  useEffect(() => {
    if (!selectedNode || selectedNode.layer !== 'WAREHOUSE') {
      setTables([]);
      return;
    }

    async function fetchTables() {
      setTablesLoading(true);
      setTablesError(null);
      
      try {
        const response = await fetch(`/api/pipeline/${selectedNode?.stackId}/nodes/${selectedNode?.id}/tables`);
        if (response.ok) {
          const data = await response.json();
          const tableList = (data.tables || []).map((t: string | { name: string }) => 
            typeof t === 'string' ? { name: t, schema: t.split('.')[1] || 'public' } : t
          );
          setTables(tableList);
          
          if (data.demo) {
            setTablesError('Scanner backend offline - showing example tables. Start the Python scanner to see real tables.');
          }
        } else {
          const error = await response.json();
          setTablesError(error.error || 'Failed to fetch tables');
        }
      } catch (err) {
        setTablesError('Failed to connect to the data source');
      } finally {
        setTablesLoading(false);
      }
    }
    
    fetchTables();
  }, [selectedNode]);

  const toggleTableSelection = (tableName: string) => {
    const newSelected = new Set(selectedTables);
    if (newSelected.has(tableName)) {
      newSelected.delete(tableName);
    } else {
      newSelected.add(tableName);
    }
    setSelectedTables(newSelected);
  };

  const selectAllTables = () => {
    const filtered = filteredTables.map(t => t.name);
    if (selectedTables.size === filtered.length) {
      setSelectedTables(new Set());
    } else {
      setSelectedTables(new Set(filtered));
    }
  };

  const runScan = async (scanTypes: string[]) => {
    if (!selectedNode || selectedTables.size === 0) return;
    
    setScanRunning(true);
    setScanProgress([]);
    
    const tablesToScan = Array.from(selectedTables);
    
    for (const scanType of scanTypes) {
      setScanProgress(prev => [...prev, { type: scanType, status: 'running' }]);
      
      try {
        const response = await fetch('/api/pipeline/scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            stackId: selectedNode.stackId,
            nodeId: selectedNode.id,
            scanTypes: [scanType],
            tables: tablesToScan,
          }),
        });
        
        if (response.ok) {
          const data = await response.json();
          setScanProgress(prev => 
            prev.map(p => p.type === scanType ? { ...p, status: 'completed', scanId: data.scanId } : p)
          );
          
          // Navigate to findings after last scan completes
          if (scanType === scanTypes[scanTypes.length - 1]) {
            setTimeout(() => {
              router.push(`/dashboard/findings?stackId=${selectedNode.stackId}`);
            }, 1000);
          }
        } else {
          const error = await response.json();
          setScanProgress(prev => 
            prev.map(p => p.type === scanType ? { ...p, status: 'failed', error: error.error } : p)
          );
        }
      } catch (err) {
        setScanProgress(prev => 
          prev.map(p => p.type === scanType ? { ...p, status: 'failed', error: 'Network error' } : p)
        );
      }
    }
    
    setScanRunning(false);
  };

  // Filter nodes by search and layer
  const filteredNodes = nodes.filter(node => {
    const matchesSearch = node.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      node.toolType.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesLayer = !layerFilter || node.layer === layerFilter;
    return matchesSearch && matchesLayer;
  });

  const warehouseNodes = filteredNodes.filter(n => n.layer === 'WAREHOUSE');
  const otherNodes = filteredNodes.filter(n => n.layer !== 'WAREHOUSE');

  const filteredTables = tables.filter(t =>
    t.name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const toolConfig = selectedNode ? TOOL_CONFIG[selectedNode.toolType] : null;
  const ToolIcon = toolConfig?.icon || Database;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  // No pipeline configured yet
  if (nodes.length === 0) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Data Sources</h1>
          <p className="text-[var(--muted)] mt-1">View and manage your connected data sources</p>
        </div>

        <div className="dashboard-card p-12 text-center">
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--accent)]/20 to-purple-500/20 flex items-center justify-center mx-auto mb-6">
            <Warehouse className="w-10 h-10 text-[var(--accent-2)]" />
          </div>
          <h2 className="text-xl font-semibold mb-3">No Pipeline Configured</h2>
          <p className="text-[var(--muted)] mb-6 max-w-md mx-auto">
            Build your data pipeline first by connecting your ingestion, transformation, warehouse, and reporting tools.
          </p>
          <Link href="/dashboard/pipeline" className="btn btn-elevated inline-flex items-center gap-2">
            <Plus className="w-4 h-4" />
            Build Your Pipeline
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold">Data Sources</h1>
          <p className="text-[var(--muted)] mt-1">
            {nodes.length} connected sources across your pipeline
          </p>
        </div>
        <Link href="/dashboard/pipeline" className="btn btn-secondary text-sm inline-flex items-center gap-2">
          <Settings className="w-4 h-4" />
          Manage Pipeline
        </Link>
      </div>

      {/* Layer Filter Pills */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setLayerFilter(null)}
          className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
            !layerFilter 
              ? 'bg-[var(--accent)] text-white' 
              : 'bg-[rgba(255,255,255,0.05)] text-[var(--muted)] hover:text-white'
          }`}
        >
          All Sources ({nodes.length})
        </button>
        {Object.entries(LAYER_CONFIG).map(([layer, config]) => {
          const count = nodes.filter(n => n.layer === layer).length;
          if (count === 0) return null;
          return (
            <button
              key={layer}
              onClick={() => setLayerFilter(layerFilter === layer ? null : layer)}
              className={`px-3 py-1.5 rounded-full text-sm transition-colors ${
                layerFilter === layer
                  ? `bg-gradient-to-r ${config.color} text-white ${config.border} border`
                  : 'bg-[rgba(255,255,255,0.05)] text-[var(--muted)] hover:text-white'
              }`}
            >
              {config.label} ({count})
            </button>
          );
        })}
          </div>

      {/* Lineage Section */}
      <div className="dashboard-card p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
              lineageInfo?.hasLineage 
                ? 'bg-gradient-to-br from-emerald-500/20 to-emerald-600/20' 
                : 'bg-gradient-to-br from-orange-500/20 to-orange-600/20'
            }`}>
              <Network className={`w-6 h-6 ${
                lineageInfo?.hasLineage ? 'text-emerald-400' : 'text-orange-400'
              }`} />
            </div>
            <div>
              <h3 className="font-semibold flex items-center gap-2">
                Data Lineage
                {lineageLoading && <Loader2 className="w-4 h-4 animate-spin text-[var(--muted)]" />}
              </h3>
              {lineageInfo?.hasLineage && lineageInfo.latest ? (
                <p className="text-sm text-[var(--muted)]">
                  {lineageInfo.latest.nodeCount} nodes • {lineageInfo.latest.edgeCount} relationships • 
                  {' '}Last updated {new Date(lineageInfo.latest.updatedAt).toLocaleDateString()}
                </p>
              ) : (
                <p className="text-sm text-orange-400">
                  No lineage built yet — Upload a dbt manifest to see relationships
                </p>
              )}
        </div>
          </div>

          <div className="flex items-center gap-3">
            {lineageInfo?.hasLineage && (
              <>
                <button
                  onClick={() => router.push('/dashboard/lineage')}
                  className="btn btn-secondary text-sm inline-flex items-center gap-2"
                >
                  <Eye className="w-4 h-4" />
                  View Lineage
                </button>
                <button
                  onClick={handleRemoveLineage}
                  className="btn text-sm inline-flex items-center gap-2 text-red-400 hover:text-red-300 hover:bg-red-500/10 border border-red-500/30"
                >
                  <Trash2 className="w-4 h-4" />
                  Remove
                </button>
              </>
            )}
            <button
              onClick={() => setLineageModalOpen(true)}
              className="btn btn-elevated text-sm inline-flex items-center gap-2"
            >
              <Upload className="w-4 h-4" />
              {lineageInfo?.hasLineage ? 'Update Lineage' : 'Upload dbt Manifest'}
            </button>
          </div>
        </div>

        {/* Quick stats if lineage exists */}
        {lineageInfo?.hasLineage && lineageInfo.latest && (
          <div className="mt-4 pt-4 border-t border-[rgba(255,255,255,0.06)] grid grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-emerald-400">{lineageInfo.latest.nodeCount}</div>
              <div className="text-xs text-[var(--muted)]">Total Nodes</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-400">{lineageInfo.latest.edgeCount}</div>
              <div className="text-xs text-[var(--muted)]">Relationships</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-purple-400">{lineageInfo.latest.rootCount}</div>
              <div className="text-xs text-[var(--muted)]">Root Sources</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-orange-400">{lineageInfo.latest.leafCount}</div>
              <div className="text-xs text-[var(--muted)]">End Tables</div>
            </div>
          </div>
        )}
      </div>

      {/* All Integrated Tables Section */}
      {(allTables.length > 0 || (nodes.some(n => n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')))) && (
        <div className="dashboard-card overflow-hidden">
          <div 
            className="p-4 flex items-center justify-between cursor-pointer hover:bg-[rgba(255,255,255,0.02)] transition-colors"
            onClick={() => setShowAllTables(!showAllTables)}
          >
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-600/20 flex items-center justify-center">
                <Database className="w-6 h-6 text-blue-400" />
              </div>
              <div>
                <h3 className="font-semibold flex items-center gap-2">
                  Integrated Tables & Datasets
                  {allTablesLoading && <Loader2 className="w-4 h-4 animate-spin text-[var(--muted)]" />}
                </h3>
                <p className="text-sm text-[var(--muted)]">
                  {allTables.length > 0 
                    ? `${allTables.length} tables discovered across ${new Set(allTables.map(t => t.dataset)).size} datasets`
                    : 'Build lineage to discover all tables in your warehouse'
                  }
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm text-[var(--muted)]">
                {showAllTables ? 'Click to collapse' : 'Click to expand'}
              </span>
              <ChevronRight className={`w-5 h-5 text-[var(--muted)] transition-transform ${showAllTables ? 'rotate-90' : ''}`} />
            </div>
          </div>

          {showAllTables && allTables.length === 0 && (
            <div className="p-8 border-t border-[rgba(255,255,255,0.06)] text-center">
              <Database className="w-12 h-12 text-[var(--muted)] mx-auto mb-4 opacity-50" />
              <h4 className="font-medium mb-2">No Tables Discovered Yet</h4>
              <p className="text-sm text-[var(--muted)] mb-4">
                Build your data lineage to discover and catalog all tables across your warehouses.
              </p>
              <button
                onClick={() => setLineageModalOpen(true)}
                className="btn btn-elevated text-sm inline-flex items-center gap-2"
              >
                <GitBranch className="w-4 h-4" />
                Build Lineage
              </button>
            </div>
          )}

          {showAllTables && allTables.length > 0 && (
            <>
              {/* Search and filters */}
              <div className="p-4 border-t border-[rgba(255,255,255,0.06)] flex items-center gap-4">
                <div className="relative flex-1 max-w-md">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted)]" />
                  <input
                    type="text"
                    placeholder="Search tables..."
                    value={tableSearchQuery}
                    onChange={(e) => setTableSearchQuery(e.target.value)}
                    className="w-full pl-10 pr-4 py-2 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-sm focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>
                <div className="flex items-center gap-2">
                  {/* Dataset filter pills */}
                  {Array.from(new Set(allTables.map(t => t.dataset))).slice(0, 5).map(dataset => (
                    <button
                      key={dataset}
                      onClick={() => setTableSearchQuery(dataset)}
                      className="px-3 py-1.5 text-xs rounded-full bg-[rgba(255,255,255,0.05)] text-[var(--muted)] hover:bg-[rgba(255,255,255,0.1)] hover:text-white transition-colors"
                    >
                      {dataset}
                    </button>
                  ))}
                </div>
              </div>

              {/* Dataset breakdown */}
              <div className="px-4 pb-4 grid grid-cols-2 md:grid-cols-4 gap-3">
                {Array.from(new Set(allTables.map(t => t.dataset))).map(dataset => {
                  const tablesInDataset = allTables.filter(t => t.dataset === dataset);
                  const views = tablesInDataset.filter(t => t.nodeType === 'VIEW' || t.nodeType === 'MATERIALIZED_VIEW').length;
                  const tables = tablesInDataset.length - views;
                  
                  return (
                    <div 
                      key={dataset}
                      className="p-3 rounded-xl bg-[rgba(255,255,255,0.02)] border border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)] transition-colors cursor-pointer"
                      onClick={() => setTableSearchQuery(dataset)}
                    >
                      <div className="flex items-center gap-2 mb-2">
                        <div className="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center">
                          <Database className="w-4 h-4 text-indigo-400" />
                        </div>
                        <span className="font-medium text-sm truncate">{dataset}</span>
                      </div>
                      <div className="flex items-center gap-3 text-xs text-[var(--muted)]">
                        <span>{tables} tables</span>
                        {views > 0 && <span>{views} views</span>}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Tables list */}
              <div className="border-t border-[rgba(255,255,255,0.06)] max-h-[400px] overflow-y-auto">
                {allTables
                  .filter(t => 
                    t.table.toLowerCase().includes(tableSearchQuery.toLowerCase()) ||
                    t.dataset.toLowerCase().includes(tableSearchQuery.toLowerCase())
                  )
                  .map((table, idx) => (
                    <div 
                      key={`${table.table}-${idx}`}
                      className="px-4 py-3 flex items-center gap-3 border-b border-[rgba(255,255,255,0.04)] last:border-b-0 hover:bg-[rgba(255,255,255,0.02)]"
                    >
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                        table.nodeType === 'VIEW' ? 'bg-purple-500/20' :
                        table.nodeType === 'MATERIALIZED_VIEW' ? 'bg-orange-500/20' :
                        table.nodeType === 'SOURCE' ? 'bg-blue-500/20' :
                        'bg-emerald-500/20'
                      }`}>
                        <Database className={`w-4 h-4 ${
                          table.nodeType === 'VIEW' ? 'text-purple-400' :
                          table.nodeType === 'MATERIALIZED_VIEW' ? 'text-orange-400' :
                          table.nodeType === 'SOURCE' ? 'text-blue-400' :
                          'text-emerald-400'
                        }`} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-sm truncate">{table.table}</div>
                        <div className="text-xs text-[var(--muted)]">
                          {table.dataset}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          table.nodeType === 'VIEW' ? 'bg-purple-500/20 text-purple-400' :
                          table.nodeType === 'MATERIALIZED_VIEW' ? 'bg-orange-500/20 text-orange-400' :
                          table.nodeType === 'SOURCE' ? 'bg-blue-500/20 text-blue-400' :
                          'bg-emerald-500/20 text-emerald-400'
                        }`}>
                          {table.nodeType}
                        </span>
                      </div>
                    </div>
                  ))
                }
                
                {allTables.filter(t => 
                  t.table.toLowerCase().includes(tableSearchQuery.toLowerCase()) ||
                  t.dataset.toLowerCase().includes(tableSearchQuery.toLowerCase())
                ).length === 0 && (
                  <div className="p-8 text-center text-[var(--muted)]">
                    No tables match your search
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Source Selector Sidebar */}
          <div className="lg:col-span-1 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider">
              Connected Sources
            </h2>
          </div>

            <div className="space-y-2">
            {filteredNodes.map(node => {
              const config = TOOL_CONFIG[node.toolType] || { icon: Database, color: '#666', label: node.toolType };
              const NodeIcon = config.icon;
              const statusConfig = STATUS_CONFIG[node.status] || STATUS_CONFIG.PENDING;
              const StatusIcon = statusConfig.icon;
              const isSelected = selectedNode?.id === node.id;
              const isWarehouse = node.layer === 'WAREHOUSE';
              const isConnected = node.status === 'CONNECTED' || node.status === 'HEALTHY';
                
                return (
                  <button
                  key={node.id}
                  onClick={() => isWarehouse && isConnected && setSelectedNode(node)}
                  disabled={!isWarehouse || !isConnected}
                    className={`w-full p-4 rounded-xl text-left transition-all border ${
                    !isWarehouse || !isConnected
                      ? 'opacity-60 cursor-not-allowed bg-[rgba(255,255,255,0.01)] border-[rgba(255,255,255,0.04)]'
                        : isSelected
                          ? 'bg-[rgba(139,11,16,0.15)] border-[var(--accent)]'
                          : 'bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div 
                      className="w-10 h-10 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: `${config.color}20` }}
                      >
                      <NodeIcon className="w-5 h-5" style={{ color: config.color }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                        <h3 className="font-medium text-sm truncate">{node.name}</h3>
                        <StatusIcon className={`w-3.5 h-3.5 flex-shrink-0 ${statusConfig.color}`} />
                        </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs text-[var(--muted)]">{config.label}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${LAYER_CONFIG[node.layer].border} bg-gradient-to-r ${LAYER_CONFIG[node.layer].color}`}>
                          {LAYER_CONFIG[node.layer].label}
                        </span>
                      </div>
                    </div>
                  </div>
                  
                  {node.findingsCount > 0 && (
                    <div className="mt-3 flex items-center gap-2 text-xs">
                      {node.criticalCount > 0 && (
                        <span className="px-2 py-0.5 rounded bg-red-500/20 text-red-400">
                          {node.criticalCount} critical
                        </span>
                      )}
                      {node.highCount > 0 && (
                        <span className="px-2 py-0.5 rounded bg-orange-500/20 text-orange-400">
                          {node.highCount} high
                        </span>
                      )}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
            
          {/* Add More Sources */}
            <Link 
            href="/dashboard/pipeline" 
              className="flex items-center gap-2 p-4 rounded-xl border border-dashed border-[rgba(255,255,255,0.1)] text-[var(--muted)] hover:text-white hover:border-[rgba(255,255,255,0.2)] transition-colors"
            >
            <Plus className="w-5 h-5" />
            <span className="text-sm">Add More Sources</span>
            </Link>

          {/* Quick Stats */}
          <div className="mt-6 pt-6 border-t border-[rgba(255,255,255,0.06)]">
            <h2 className="text-sm font-medium text-[var(--muted)] uppercase tracking-wider mb-3">Pipeline Overview</h2>
            <div className="space-y-2">
              {Object.entries(LAYER_CONFIG).map(([layer, config]) => {
                const layerNodes = nodes.filter(n => n.layer === layer);
                const healthyCount = layerNodes.filter(n => n.status === 'HEALTHY' || n.status === 'CONNECTED').length;
                return (
                  <div key={layer} className="flex items-center justify-between text-sm">
                    <span className="text-[var(--muted)]">{config.label}</span>
                    <span className={healthyCount === layerNodes.length ? 'text-emerald-400' : 'text-yellow-400'}>
                      {healthyCount}/{layerNodes.length}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
          </div>

          {/* Tables Panel */}
          <div className="lg:col-span-3">
          {!selectedNode ? (
              <div className="dashboard-card p-12 text-center">
              <Database className="w-12 h-12 text-[var(--muted)] mx-auto mb-4" />
              <h3 className="text-lg font-medium mb-2">Select a Warehouse</h3>
              <p className="text-[var(--muted)]">
                Select a connected warehouse from the sidebar to view and scan tables
              </p>
            </div>
          ) : selectedNode.layer !== 'WAREHOUSE' ? (
            <div className="dashboard-card p-12 text-center">
              <ToolIcon className="w-12 h-12 mx-auto mb-4" style={{ color: toolConfig?.color }} />
              <h3 className="text-lg font-medium mb-2">{selectedNode.name}</h3>
              <p className="text-[var(--muted)] mb-4">
                This is a {LAYER_CONFIG[selectedNode.layer].label.toLowerCase()} tool. 
                Table scanning is available for warehouses only.
              </p>
              <Link href={`/dashboard/pipeline?nodeId=${selectedNode.id}`} className="btn btn-secondary inline-flex items-center gap-2">
                <Settings className="w-4 h-4" />
                Configure in Pipeline
              </Link>
              </div>
            ) : (
              <div className="dashboard-card overflow-hidden">
                {/* Tables Header */}
                <div className="p-4 border-b border-[var(--border-dim)] flex items-center justify-between gap-4">
                  <div className="flex items-center gap-4 flex-1">
                  <div className="flex items-center gap-3">
                    <div 
                      className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ backgroundColor: `${toolConfig?.color}20` }}
                    >
                      <ToolIcon className="w-4 h-4" style={{ color: toolConfig?.color }} />
                    </div>
                    <h2 className="font-semibold">
                      Tables in {selectedNode.name}
                    </h2>
                  </div>
                    <div className="relative flex-1 max-w-xs">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--muted)]" />
                      <input
                        type="text"
                        placeholder="Search tables..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-10 pr-4 py-2 bg-[rgba(255,255,255,0.03)] border border-[rgba(255,255,255,0.08)] rounded-lg text-sm focus:outline-none focus:border-[var(--accent)]"
                      />
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3">
                    {selectedTables.size > 0 && (
                      <span className="text-sm text-[var(--muted)]">
                        {selectedTables.size} selected
                      </span>
                    )}
                    <button
                      onClick={() => setScanModalOpen(true)}
                      disabled={selectedTables.size === 0}
                    className="btn btn-elevated text-sm disabled:opacity-50 inline-flex items-center gap-2"
                    >
                    <Play className="w-4 h-4" />
                      Scan Selected
                    </button>
                  </div>
                </div>

                {/* Warning Banner */}
                {tablesError && (
                  <div className="p-3 bg-amber-500/10 border-b border-amber-500/20 flex items-center gap-3">
                  <AlertCircle className="w-5 h-5 text-amber-400 flex-shrink-0" />
                    <span className="text-sm text-amber-400">{tablesError}</span>
                  </div>
                )}

                {/* Tables List */}
                {tablesLoading ? (
                  <div className="p-12 text-center">
                    <div className="animate-spin w-8 h-8 border-2 border-[var(--accent)] border-t-transparent rounded-full mx-auto mb-4" />
                    <p className="text-[var(--muted)]">Discovering tables...</p>
                  </div>
                ) : (
                  <div className="divide-y divide-[var(--border-dim)]">
                    {/* Select All Row */}
                    <div className="p-4 bg-[rgba(255,255,255,0.02)] flex items-center gap-3">
                      <button
                        onClick={selectAllTables}
                        className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${
                          selectedTables.size === filteredTables.length && filteredTables.length > 0
                            ? 'bg-[var(--accent)] border-[var(--accent)]'
                            : 'border-[rgba(255,255,255,0.2)] hover:border-[rgba(255,255,255,0.4)]'
                        }`}
                      >
                        {selectedTables.size === filteredTables.length && filteredTables.length > 0 && (
                        <CheckCircle className="w-3 h-3 text-white" />
                        )}
                      </button>
                      <span className="text-sm font-medium">
                        {filteredTables.length} tables found
                      </span>
                    </div>

                    {/* Table Rows */}
                    <div className="max-h-[500px] overflow-y-auto">
                      {filteredTables.map((table) => (
                        <div
                          key={table.name}
                          onClick={() => toggleTableSelection(table.name)}
                          className={`p-4 flex items-center gap-3 cursor-pointer transition-colors ${
                            selectedTables.has(table.name)
                              ? 'bg-[rgba(139,11,16,0.1)]'
                              : 'hover:bg-[rgba(255,255,255,0.02)]'
                          }`}
                        >
                          <div
                            className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${
                              selectedTables.has(table.name)
                                ? 'bg-[var(--accent)] border-[var(--accent)]'
                                : 'border-[rgba(255,255,255,0.2)]'
                            }`}
                          >
                            {selectedTables.has(table.name) && (
                            <CheckCircle className="w-3 h-3 text-white" />
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="font-mono text-sm truncate">{table.name}</div>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-[var(--muted)] px-2 py-1 rounded bg-[rgba(255,255,255,0.05)]">
                              {table.schema}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>

                    {filteredTables.length === 0 && !tablesLoading && (
                      <div className="p-12 text-center">
                        <p className="text-[var(--muted)]">
                          {searchQuery ? 'No tables match your search' : 'No tables found'}
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

      {/* Scan Modal */}
      {scanModalOpen && selectedNode && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--card)] border border-[rgba(255,255,255,0.08)] rounded-2xl max-w-md w-full shadow-2xl">
            <div className="p-6 border-b border-[rgba(255,255,255,0.06)]">
              <h2 className="text-lg font-semibold">Run Scan</h2>
              <p className="text-sm text-[var(--muted)] mt-1">
                Select which scans to run on {selectedTables.size} selected tables
              </p>
            </div>

            {scanRunning ? (
              <div className="p-6 space-y-4">
                {scanProgress.map((progress, idx) => (
                  <div key={idx} className="flex items-center gap-3">
                    {progress.status === 'running' && (
                      <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
                    )}
                    {progress.status === 'completed' && (
                      <CheckCircle className="w-5 h-5 text-emerald-400" />
                    )}
                    {progress.status === 'failed' && (
                      <XCircle className="w-5 h-5 text-red-400" />
                    )}
                    <span className="capitalize">{progress.type} Scan</span>
                    <span className={`ml-auto text-sm ${
                      progress.status === 'completed' ? 'text-emerald-400' :
                      progress.status === 'failed' ? 'text-red-400' :
                      'text-[var(--muted)]'
                    }`}>
                      {progress.status}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-6 space-y-3">
                <button
                  onClick={() => runScan(['freshness'])}
                  className="w-full p-4 rounded-xl text-left border border-[rgba(255,255,255,0.08)] hover:border-[var(--accent)] hover:bg-[rgba(139,11,16,0.1)] transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                      <Clock className="w-5 h-5 text-blue-400" />
                    </div>
                    <div>
                      <h3 className="font-medium">Freshness Scan</h3>
                      <p className="text-sm text-[var(--muted)]">Check data staleness</p>
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => runScan(['quality'])}
                  className="w-full p-4 rounded-xl text-left border border-[rgba(255,255,255,0.08)] hover:border-[var(--accent)] hover:bg-[rgba(139,11,16,0.1)] transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                      <CheckCircle className="w-5 h-5 text-emerald-400" />
                    </div>
                    <div>
                      <h3 className="font-medium">Quality Scan</h3>
                      <p className="text-sm text-[var(--muted)]">Null rates, duplicates</p>
                    </div>
                  </div>
                </button>

                <button
                  onClick={() => runScan(['freshness', 'quality'])}
                  className="w-full p-4 rounded-xl text-left border border-[var(--accent)] bg-[rgba(139,11,16,0.1)] hover:bg-[rgba(139,11,16,0.15)] transition-all"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-[var(--accent)]/30 flex items-center justify-center">
                      <BarChart3 className="w-5 h-5 text-[var(--accent-2)]" />
                    </div>
                    <div>
                      <h3 className="font-medium">Full Scan</h3>
                      <p className="text-sm text-[var(--muted)]">Freshness + Quality</p>
                    </div>
                    <span className="ml-auto px-2 py-0.5 text-xs font-medium rounded bg-[var(--accent)] text-white">
                      Recommended
                    </span>
                  </div>
                </button>
              </div>
            )}

            <div className="p-6 border-t border-[rgba(255,255,255,0.06)] flex justify-end">
              <button
                onClick={() => {
                  setScanModalOpen(false);
                  setScanProgress([]);
                }}
                disabled={scanRunning}
                className="px-4 py-2 text-sm text-[var(--muted)] hover:text-white transition-colors disabled:opacity-50"
              >
                {scanRunning ? 'Running...' : 'Cancel'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Lineage Upload Modal */}
      {lineageModalOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[var(--card)] border border-[rgba(255,255,255,0.08)] rounded-2xl max-w-lg w-full shadow-2xl">
            <div className="p-6 border-b border-[rgba(255,255,255,0.06)]">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-orange-500/20 to-orange-600/20 flex items-center justify-center">
                  <Network className="w-6 h-6 text-orange-400" />
    </div>
                <div>
                  <h2 className="text-lg font-semibold">Build Data Lineage</h2>
                  <p className="text-sm text-[var(--muted)]">
                    Upload your dbt manifest.json to map table relationships
                  </p>
                </div>
              </div>
            </div>

            <div className="p-6 space-y-6">
              {/* Build from Warehouse Option */}
              {nodes.some(n => n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')) && (
                <div className="space-y-3">
                  <h4 className="font-medium text-sm flex items-center gap-2">
                    <Database className="w-4 h-4 text-blue-400" />
                    Option 1: Build from Warehouse Query History
                  </h4>
                  <button
                    onClick={handleBuildFromWarehouse}
                    disabled={buildingFromWarehouse || uploadingManifest}
                    className="w-full p-4 rounded-xl text-left border border-blue-500/30 bg-blue-500/5 hover:bg-blue-500/10 hover:border-blue-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
                        {buildingFromWarehouse ? (
                          <Loader2 className="w-5 h-5 text-blue-400 animate-spin" />
                        ) : (
                          <GitBranch className="w-5 h-5 text-blue-400" />
                        )}
                      </div>
                      <div className="flex-1">
                        <h3 className="font-medium">Build from {nodes.find(n => n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY'))?.name || 'Warehouse'}</h3>
                        <p className="text-sm text-[var(--muted)]">
                          {buildingFromWarehouse 
                            ? buildLineageProgress || 'Building lineage...'
                            : 'Analyze query history to extract table relationships'
                          }
                        </p>
                      </div>
                      {!buildingFromWarehouse && (
                        <span className="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400">
                          Recommended
                        </span>
                      )}
                    </div>
                  </button>
                  <p className="text-xs text-[var(--muted)] ml-4">
                    Extracts lineage from BigQuery INFORMATION_SCHEMA.JOBS, Snowflake QUERY_HISTORY, etc.
                  </p>
                </div>
              )}

              {/* Divider */}
              {nodes.some(n => n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')) && (
                <div className="flex items-center gap-4">
                  <div className="flex-1 h-px bg-[rgba(255,255,255,0.1)]" />
                  <span className="text-xs text-[var(--muted)]">OR</span>
                  <div className="flex-1 h-px bg-[rgba(255,255,255,0.1)]" />
                </div>
              )}

              {/* Upload Area */}
              <div className="space-y-3">
                <h4 className="font-medium text-sm flex items-center gap-2">
                  <FileJson className="w-4 h-4 text-orange-400" />
                  {nodes.some(n => n.layer === 'WAREHOUSE' && (n.status === 'CONNECTED' || n.status === 'HEALTHY')) 
                    ? 'Option 2: Upload dbt Manifest' 
                    : 'Upload dbt Manifest'
                  }
                </h4>
                <div 
                  className="border-2 border-dashed border-[rgba(255,255,255,0.15)] rounded-xl p-6 text-center hover:border-[var(--accent)] transition-colors cursor-pointer relative"
                  onDragOver={(e) => {
                    e.preventDefault();
                    e.currentTarget.classList.add('border-[var(--accent)]', 'bg-[rgba(139,11,16,0.1)]');
                  }}
                  onDragLeave={(e) => {
                    e.currentTarget.classList.remove('border-[var(--accent)]', 'bg-[rgba(139,11,16,0.1)]');
                  }}
                  onDrop={(e) => {
                    e.preventDefault();
                    e.currentTarget.classList.remove('border-[var(--accent)]', 'bg-[rgba(139,11,16,0.1)]');
                    const file = e.dataTransfer.files[0];
                    if (file && file.name.endsWith('.json')) {
                      handleManifestUpload(file);
                    } else {
                      alert('Please upload a JSON file');
                    }
                  }}
                >
                  <input
                    type="file"
                    accept=".json"
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        handleManifestUpload(file);
                      }
                    }}
                    disabled={uploadingManifest || buildingFromWarehouse}
                  />
                  
                  {uploadingManifest ? (
                    <div className="flex flex-col items-center">
                      <Loader2 className="w-10 h-10 text-[var(--accent)] animate-spin mb-3" />
                      <p className="text-[var(--muted)]">Processing manifest...</p>
                    </div>
                  ) : (
                    <>
                      <FileJson className="w-10 h-10 text-[var(--muted)] mx-auto mb-3" />
                      <p className="font-medium mb-1 text-sm">Drop your manifest.json here</p>
                      <p className="text-xs text-[var(--muted)]">or click to browse</p>
                    </>
                  )}
                </div>
                <p className="text-xs text-[var(--muted)] ml-4">
                  Run <code className="px-1 py-0.5 bg-[rgba(255,255,255,0.05)] rounded text-xs font-mono">dbt compile</code> and upload <code className="px-1 py-0.5 bg-[rgba(255,255,255,0.05)] rounded text-xs font-mono">target/manifest.json</code>
                </p>
              </div>

              {/* Current lineage status */}
              {lineageInfo?.latest && (
                <div className="flex items-center justify-between p-4 bg-[rgba(255,255,255,0.02)] rounded-xl">
                  <div className="flex items-center gap-3">
                    <div className={`w-2 h-2 rounded-full ${
                      lineageInfo.latest.status === 'ready' ? 'bg-emerald-400' :
                      lineageInfo.latest.status === 'building' ? 'bg-yellow-400 animate-pulse' :
                      'bg-red-400'
                    }`} />
                    <div>
                      <p className="text-sm font-medium">Current Lineage</p>
                      <p className="text-xs text-[var(--muted)]">
                        {lineageInfo.latest.nodeCount} nodes • Source: {lineageInfo.latest.source}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs text-[var(--muted)]">
                    {new Date(lineageInfo.latest.updatedAt).toLocaleString()}
                  </span>
                </div>
              )}
            </div>

            <div className="p-6 border-t border-[rgba(255,255,255,0.06)] flex justify-end gap-3">
              <button
                onClick={() => setLineageModalOpen(false)}
                disabled={uploadingManifest}
                className="px-4 py-2 text-sm text-[var(--muted)] hover:text-white transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
