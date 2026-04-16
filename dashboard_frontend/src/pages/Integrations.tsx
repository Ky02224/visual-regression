import React from 'react';
import { 
  Terminal, 
  Key, 
  Copy, 
  Check, 
  Eye, 
  EyeOff, 
  Cpu, 
  Github, 
  Gitlab, 
  Webhook, 
  ExternalLink,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';


export function Integrations() {
  return (
    <div className="p-8 corporate-grid min-h-screen">
      <div className="max-w-6xl mx-auto space-y-12">
        {/* Header */}
        <header className="border-b border-slate-200 dark:border-slate-800 pb-8">
          <h2 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">CI/CD Integrations</h2>
          <p className="text-slate-500 dark:text-slate-400 font-medium">Connect The Lens to your development workflow for automated visual regression testing.</p>
        </header>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* API Tokens Module */}
          <ApiTokensModule />

          {/* Webhooks Module */}
          <WebhooksModule />

          {/* Pipeline Generator Module */}
          <div className="lg:col-span-2">
            <PipelineGeneratorModule />
          </div>

          {/* Pipeline Feed Module */}
          <div className="lg:col-span-2">
            <PipelineFeedModule />
          </div>
        </div>

      </div>
    </div>
  );
}

function ApiTokensModule() {
  const { accessKey, role } = useRole();
  const [showKey, setShowKey] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [apiKey, setApiKey] = React.useState("••••••••••••••••••••••••••••••••");
  const [isRotating, setIsRotating] = React.useState(false);

  React.useEffect(() => {
    fetch('/api/integrations')
      .then(res => res.json())
      .then(data => {
        if (data.api_key) setApiKey(data.api_key);
      })
      .catch(() => {});
  }, []);

  const handleCopy = () => {
    // If it's masked, we can't really copy the real key unless we fetch it or it's provided
    // In our case, we'll fetch the real key when "show" is clicked or just allow copying if we have it
    if (apiKey.includes('•')) {
       alert("Please rotate or reveal key to copy real token.");
       return;
    }
    navigator.clipboard.writeText(apiKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRotateKey = async () => {
    if (!window.confirm("Rotating the key will invalidate the current one. Continue?")) return;
    
    setIsRotating(true);
    try {
      const res = await fetch('/api/integrations/rotate-key', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json', 
          'X-Access-Key': accessKey || '' 
        }
      });
      
      const data = await res.json();
      if (data.ok) {
        setApiKey(data.api_key);
        setShowKey(true);
      } else {
        alert(data.error || "Failed to rotate key");
      }
    } catch (e) {
      alert("Network error. Please ensure the dashboard server is running.");
    } finally {
      setIsRotating(false);
    }
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm">
      <div className="flex items-center gap-4 mb-6">
        <div className="w-10 h-10 rounded-xl bg-slate-50 dark:bg-slate-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700">
          <Key className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">API Access Tokens</h3>
          <p className="text-xs text-slate-400 font-medium">Use this token to authenticate CI/CD requests.</p>
        </div>
      </div>

      <div className="space-y-4">
        <div className="p-4 bg-slate-900 rounded-2xl border border-slate-800 flex items-center justify-between group">
          <div className="flex-1 mr-4 overflow-hidden">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Production Key</p>
            <code className="text-sm font-mono text-blue-400 block truncate">
              {showKey ? apiKey : "••••••••••••••••••••••••••••••••"}
            </code>
          </div>
          <div className="flex items-center gap-2">
            <button 
              onClick={() => setShowKey(!showKey)}
              className="p-2 text-slate-500 hover:text-white transition-colors"
            >
              {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
            <button 
              onClick={handleCopy}
              className="p-2 text-slate-500 hover:text-white transition-colors relative"
            >
              {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
        </div>
        
        <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 uppercase tracking-tight px-2">
          <span>{isRotating ? "Generating..." : "Secure and Encrypted"}</span>
          {role === 'admin' && (
            <button 
              onClick={handleRotateKey}
              className="text-accent hover:underline disabled:opacity-50"
              disabled={isRotating}
            >
              Rotate Key
            </button>
          )}
        </div>
      </div>
    </div>
  );
}


function WebhooksModule() {
  const { accessKey, role } = useRole();
  const [url, setUrl] = React.useState("");
  const [threshold, setThreshold] = React.useState(1.0);
  const [isSaving, setIsSaving] = React.useState(false);
  const [isTesting, setIsTesting] = React.useState(false);

  React.useEffect(() => {
    fetch('/api/integrations')
      .then(res => res.json())
      .then(data => {
        setUrl(data.webhook_url || "");
        setThreshold(data.webhook_threshold || 1.0);
      });
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const res = await fetch('/api/integrations/webhooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Access-Key': accessKey || '' },
        body: JSON.stringify({ url, threshold })
      });
      if (!(await res.json()).ok) alert("Failed to save settings");
    } catch (e) {
      alert("Network error");
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    if (!url) return;
    setIsTesting(true);
    try {
      const res = await fetch('/api/integrations/test-webhook', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Access-Key': accessKey || '' },
        body: JSON.stringify({ url })
      });
      const data = await res.json();
      alert(data.ok ? "Test Success! Check your webhook destination." : "Test Failed. Check URL connectivity.");
    } catch (e) {
      alert("Test Error: Network failure");
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm flex flex-col">
      <div className="flex items-center gap-4 mb-6">
        <div className="w-10 h-10 rounded-xl bg-slate-50 dark:bg-slate-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700">
          <Webhook className="w-5 h-5" />
        </div>
        <div>
          <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Webhook Notifications</h3>
          <p className="text-xs text-slate-400 font-medium">Receive real-time alerts in your workspace.</p>
        </div>
      </div>

      <div className="space-y-6 flex-1">
        <div className="space-y-2">
          <label className="text-[10px] font-bold uppercase tracking-widest text-slate-400 px-1">Endpoint URL</label>
          <input 
            type="text" 
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://hooks.slack.com/services/..."
            className="w-full bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-xl p-3 text-sm outline-none focus:ring-2 focus:ring-accent/20 transition-all dark:text-slate-100"
          />
        </div>

        <div className="flex items-center justify-between p-4 bg-slate-50 dark:bg-slate-950 rounded-2xl border border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className={cn("w-2 h-2 rounded-full", url ? "bg-green-500" : "bg-slate-300")} />
            <span className="text-xs font-bold text-slate-700 dark:text-slate-300">
              Threshold: {threshold}% Mismatch
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button 
              onClick={handleTest}
              disabled={isTesting || !url}
              className="text-[10px] font-bold uppercase text-accent hover:underline disabled:opacity-50"
            >
              {isTesting ? "Testing..." : "Test Hook"}
            </button>
          </div>
        </div>
      </div>
      
      <div className="mt-6">
          <button 
            disabled={isSaving || role !== 'admin'}
            onClick={handleSave}
            className="w-full py-3 bg-slate-900 dark:bg-slate-800 text-white rounded-xl text-xs font-bold uppercase tracking-widest hover:bg-black transition-all disabled:opacity-50"
          >
            {isSaving ? "Saving..." : "Save Configuration"}
          </button>
      </div>
    </div>
  );
}


function PipelineGeneratorModule() {
  const [activeTab, setActiveTab] = React.useState<'github' | 'gitlab' | 'jenkins'>('github');

  const configs = {
    github: `name: Visual Regression Test
on: [push]
jobs:
  lens-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run The Lens Comparison
        uses: the-lens/action@v1
        with:
          api-key: \${{ secrets.LENS_API_KEY }}
          project-id: "PRJ-9021"
          threshold: 0.5`,
    gitlab: `visual_test:
  image: the-lens/runner:latest
  script:
    - lens compare --key $LENS_API_KEY --project PRJ-9021
  only:
    - merge_requests`,
    jenkins: `pipeline {
    agent any
    stages {
        stage('Visual Test') {
            steps {
                sh 'lens compare --key \${LENS_API_KEY} --project PRJ-9021'
            }
        }
    }
}`
  };

  return (
    <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
      <div className="p-8 border-b border-slate-100 dark:border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-slate-50 dark:bg-slate-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700">
            <Cpu className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Pipeline Generator</h3>
            <p className="text-xs text-slate-400 font-medium">Generate configuration files for your CI provider.</p>
          </div>
        </div>

        <div className="flex p-1 bg-slate-100 dark:bg-slate-800 rounded-xl">
          {(['github', 'gitlab', 'jenkins'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={cn(
                "px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all",
                activeTab === tab 
                  ? "bg-white dark:bg-slate-950 text-primary dark:text-slate-100 shadow-sm" 
                  : "text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              )}
            >
              {tab === 'github' && <Github className="w-3.5 h-3.5 inline mr-2" />}
              {tab === 'gitlab' && <Gitlab className="w-3.5 h-3.5 inline mr-2" />}
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="p-8 bg-slate-900 relative group">
        <div className="absolute top-4 right-4 opacity-0 group-hover:opacity-100 transition-opacity">
          <button className="p-2 bg-slate-800 text-slate-400 hover:text-white rounded-lg border border-slate-700">
            <Copy className="w-4 h-4" />
          </button>
        </div>
        <pre className="text-sm font-mono text-blue-300 overflow-x-auto leading-relaxed">
          {configs[activeTab]}
        </pre>
      </div>
    </div>
  );
}

function PipelineFeedModule() {
  const [runs, setRuns] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(true);

  const fetchActivity = () => {
    setLoading(true);
    fetch('/api/integrations/activity')
      .then(res => res.json())
      .then(data => {
        setRuns(data.activity || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  React.useEffect(() => {
    fetchActivity();
  }, []);

  return (
    <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm">
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-slate-50 dark:bg-slate-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700">
            <Terminal className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Recent Pipeline Activity</h3>
            <p className="text-xs text-slate-400 font-medium">Real-time feed of CI-triggered visual tests.</p>
          </div>
        </div>
        <button 
          onClick={fetchActivity}
          disabled={loading}
          className="p-2 text-slate-400 hover:text-accent transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("w-5 h-5", loading && "animate-spin")} />
        </button>
      </div>

      <div className="space-y-4">
        {loading && runs.length === 0 && (
          <div className="py-12 text-center text-xs font-bold text-slate-300 uppercase tracking-widest animate-pulse">
            Fetching activity log...
          </div>
        )}
        
        {!loading && runs.length === 0 && (
          <div className="py-12 text-center text-xs font-bold text-slate-300 uppercase tracking-widest border-2 border-dashed border-slate-100 dark:border-slate-800 rounded-2xl">
            No integrated activity detected yet.
          </div>
        )}

        {runs.map((run) => (
          <div key={run.id} className="flex items-center justify-between p-4 rounded-2xl border border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 transition-all group cursor-pointer">
            <div className="flex items-center gap-4">
              <div className={cn(
                "w-10 h-10 rounded-full flex items-center justify-center",
                run.status === 'success' ? "bg-green-50 text-green-500" : "bg-red-50 text-red-500"
              )}>
                {run.status === 'success' ? <CheckCircle2 className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-slate-900 dark:text-slate-100 text-sm">{run.message}</span>
                  <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-950 text-slate-500 rounded text-[10px] font-bold uppercase tracking-tight">
                    {run.branch}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1">
                  <span className="text-[10px] font-mono text-slate-400">#{run.id}</span>
                  <div className="flex items-center gap-1 text-[10px] text-slate-400 font-medium">
                    <Clock className="w-3 h-3" />
                    {new Date(run.timestamp * 1000).toLocaleString()}
                  </div>
                </div>
              </div>
            </div>
            <ExternalLink className="w-4 h-4 text-slate-300 group-hover:text-accent transition-colors" />
          </div>
        ))}
      </div>
    </div>
  );
}


