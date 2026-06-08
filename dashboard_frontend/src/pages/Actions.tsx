import { PageHeader } from '../components/ui/PageHeader';
import React from 'react';
import { 
  Camera, 
  GitBranch, 
  RefreshCw, 
  Diff,
  Search,
  Monitor,
  Smartphone,
  Globe,
  History,
  Zap,
  Play,
  X,
  Loader2,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  Lock
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';

type ActionTab = 'single' | 'multiple' | 'sync' | 'compare';

const tabs = [
  { id: 'single', label: 'Single Capture', icon: Camera },
  { id: 'multiple', label: 'Multiple Capture', icon: GitBranch },
  { id: 'sync', label: 'Sync & Replace', icon: RefreshCw },
  { id: 'compare', label: 'Run Comparison', icon: Diff },
] as const;

export function Actions() {
  const { can, role } = useRole();
  const [activeTab, setActiveTab] = React.useState<ActionTab>('single');
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [status, setStatus] = React.useState<{type: 'success' | 'error', message: string} | null>(null);
  const [baselineNames, setBaselineNames] = React.useState<string[]>([]);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => setBaselineNames((data.baselines || []).map((b: any) => b.name)))
      .catch(() => {});
  }, []);

  const handleAction = async (endpoint: string, payload: any) => {
    setIsExecuting(true);
    setStatus(null);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (result.ok) {
        setStatus({ type: 'success', message: 'Action completed. Results are being processed.' });
      } else {
        setStatus({ type: 'error', message: result.error || 'Action failed.' });
      }
    } catch (err) {
      setStatus({ type: 'error', message: 'Network error. Please try again.' });
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <div className="p-8 min-h-screen transition-colors duration-300">
      <div className="max-w-4xl mx-auto space-y-12">
        <PageHeader title="System actions" description="Capture, sync, and compare visual baselines." />

        {/* Tab Navigation */}
        <div className="flex flex-wrap items-center gap-2 p-1.5 bg-[var(--surface)] border border-[var(--outline)] rounded-md shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as ActionTab)}
              className={cn(
                "flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-300",
                activeTab === tab.id 
                  ? "bg-primary text-white shadow-lg shadow-primary/20" 
                  : "text-[var(--on-surface-variant)] hover:text-primary hover:bg-slate-50 dark:hover:bg-slate-800"
              )}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Active Action Card */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="bg-[var(--surface)] rounded-md border border-[var(--outline)] p-10 shadow-sm relative overflow-hidden"
          >
            {/* Background Accent */}
            <div className="absolute top-0 right-0 w-64 h-64 bg-accent/5 rounded-full -mr-32 -mt-32 blur-3xl" />

            <div className="relative z-10">
              <div className="flex items-center gap-4 mb-8">
                <div className="w-12 h-12 rounded-md bg-stone-50 dark:bg-zinc-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700 shadow-sm">
                  {React.createElement(tabs.find(t => t.id === activeTab)!.icon, { className: "w-6 h-6" })}
                </div>
                <div>
                  <h3 className="text-2xl font-bold text-[var(--on-surface)]">
                    {tabs.find(t => t.id === activeTab)?.label}
                  </h3>
                  <p className="text-xs text-[var(--on-surface-variant)] font-medium tracking-tight mt-0.5">
                    {activeTab === 'single' && "Capture a single page screenshot as a new baseline."}
                    {activeTab === 'multiple' && "Capture multiple pages from a target website."}
                    {activeTab === 'sync' && "Replace an existing baseline with a newer one."}
                    {activeTab === 'compare' && "Compare a baseline against a live URL."}
                  </p>
                </div>
              </div>

              <div className="space-y-8">
                {role === 'viewer' ? (
                  <div className="p-12 border-2 border-dashed border-[var(--outline)] rounded-md flex flex-col items-center justify-center text-center space-y-4">
                    <div className="p-4 bg-stone-50 dark:bg-zinc-800 rounded-full text-slate-300">
                      <Lock className="w-8 h-8" />
                    </div>
                    <div>
                      <h4 className="text-lg font-bold text-[var(--on-surface)]">Elevated Access Required</h4>
                      <p className="text-sm text-slate-500 max-w-xs mx-auto mt-1">Requires Developer or Admin access to run actions.</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {activeTab === 'single' && <SingleCaptureForm onAction={(p) => handleAction('/api/actions/create-baseline', p)} disabled={isExecuting} />}
                    {activeTab === 'multiple' && <MultipleCaptureForm onAction={(p) => handleAction('/api/actions/create-multiple-baselines', p)} disabled={isExecuting} />}
                    {activeTab === 'sync' && <SyncReplaceForm onAction={(p) => handleAction('/api/actions/update-baseline', p)} disabled={isExecuting} baselineNames={baselineNames} />}
                    {activeTab === 'compare' && <RunComparisonForm onAction={(p) => handleAction('/api/actions/compare', p)} disabled={isExecuting} baselineNames={baselineNames} />}
                  </>
                )}
              </div>

              {/* Status Notifications */}
              <AnimatePresence>
                {status && (
                  <motion.div 
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className={cn(
                      "mt-8 p-6 rounded-md flex items-center gap-4 border",
                      status.type === 'success' 
                        ? "bg-green-50 dark:bg-green-900/10 border-green-100 dark:border-green-800/20 text-green-800 dark:text-green-400" 
                        : "bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-800/20 text-red-800 dark:text-red-400"
                    )}
                  >
                    {status.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                    <p className="text-sm font-medium">{status.message}</p>
                    <button onClick={() => setStatus(null)} className="ml-auto opacity-50 hover:opacity-100">
                      <X className="w-4 h-4" />
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Loading Overlay */}
            <AnimatePresence>
              {isExecuting && (
                <motion.div 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 z-50 bg-white/60 dark:bg-slate-950/60 backdrop-blur-sm flex flex-col items-center justify-center space-y-4"
                >
                  <div className="relative">
                    <div className="w-16 h-16 border-4 border-primary/20 rounded-full animate-spin" />
                    <Loader2 className="w-8 h-8 text-primary absolute inset-1/2 -ml-4 -mt-4 animate-spin" />
                  </div>
                  <div className="text-center">
                    <p className="text-lg font-bold text-[var(--on-surface)] font-medium">Running...</p>
                    <p className="text-xs text-slate-500 font-medium tracking-tight">Capturing screenshots, please wait...</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </AnimatePresence>

      </div>
    </div>
  );
}

function SingleCaptureForm({ onAction, disabled }: { onAction: (p: any) => void, disabled: boolean }) {
  const [url, setUrl] = React.useState('');
  const [name, setName] = React.useState('');
  const [browser, setBrowser] = React.useState('Chrome');
  const [device, setDevice] = React.useState('Desktop');
  const [locale, setLocale] = React.useState('en-US');

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      <div className="space-y-6">
        <FormItem label="Target URL" placeholder="https://example.com/page" value={url} onChange={setUrl} />
        <FormItem label="Baseline Label" placeholder="e.g., Homepage - Mobile" value={name} onChange={setName} />
        <div className="grid grid-cols-3 gap-4">
          <FormSelect label="Browser" options={['Chrome', 'Safari', 'Firefox']} value={browser} onChange={setBrowser} />
          <FormSelect label="Device" options={['Desktop', 'iPhone 13', 'Pixel 6']} value={device} onChange={setDevice} />
          <FormSelect label="Locale" options={['en-US', 'zh-CN', 'ms-MY']} value={locale} onChange={setLocale} />
        </div>
      </div>
      <div className="bg-slate-50 dark:bg-slate-900/50 rounded-md border border-slate-100 dark:border-slate-800 p-6 flex flex-col justify-between">
        <div className="space-y-3">
          <h4 className="text-[10px] font-bold font-medium text-[var(--on-surface-variant)]">How it works</h4>
          <p className="text-sm text-slate-600 dark:text-[var(--on-surface-variant)] leading-relaxed">
            Opens a headless browser, waits for network idle (500ms), then captures a full-page screenshot at the specified viewport.
          </p>
        </div>
        <button 
          onClick={() => onAction({ url, name, browser, device, locale })}
          disabled={disabled || !url || !name}
          className="w-full py-4 bg-primary text-white rounded-xl font-bold text-sm shadow-lg shadow-primary/20 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
        >
          <Camera className="w-4 h-4" /> Capture
        </button>
      </div>
    </div>
  );
}

function MultipleCaptureForm({ onAction, disabled }: { onAction: (p: any) => void, disabled: boolean }) {
  const [url, setUrl] = React.useState('');
  const [browser, setBrowser] = React.useState('Chrome');
  const [device, setDevice] = React.useState('Desktop');
  const [locale, setLocale] = React.useState('en-US');
  const [concurrent, setConcurrent] = React.useState('4');

  return (
    <div className="space-y-8">
      <div className="p-6 bg-slate-50 dark:bg-slate-900/50 rounded-md border border-slate-100 dark:border-slate-800 space-y-6">
        <FormItem label="Website URL" placeholder="https://example.com" value={url} onChange={setUrl} />
        <div className="grid grid-cols-3 gap-4">
          <FormSelect label="Browser" options={['Chrome', 'Safari', 'Firefox']} value={browser} onChange={setBrowser} />
          <FormSelect label="Device" options={['Desktop', 'iPhone 13', 'Pixel 6']} value={device} onChange={setDevice} />
          <FormSelect label="Locale" options={['en-US', 'zh-CN', 'ms-MY']} value={locale} onChange={setLocale} />
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <FormSelect label="Concurrent Instances" options={['1', '2', '4', '8']} value={concurrent} onChange={setConcurrent} />
        <div className="flex items-end">
          <button 
            onClick={() => onAction({ url, browser, device, locale, concurrency: parseInt(concurrent), overwrite: true })}
            disabled={disabled || !url}
            className="w-full py-4 bg-primary text-white rounded-xl font-bold text-sm shadow-lg shadow-primary/20 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
          >
            <Play className="w-4 h-4" /> Start Capture Run
          </button>
        </div>
      </div>
    </div>
  );
}

function SyncReplaceForm({ onAction, disabled, baselineNames }: { onAction: (p: any) => void, disabled: boolean, baselineNames: string[] }) {
  const [oldBaseline, setOldBaseline] = React.useState('');
  const [newBaseline, setNewBaseline] = React.useState('');

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <FormSelect label="Select Old Baseline" options={baselineNames} value={oldBaseline} onChange={setOldBaseline} />
        <FormSelect label="Select New Baseline" options={baselineNames} value={newBaseline} onChange={setNewBaseline} />
      </div>
      <div className="p-6 bg-amber-50 dark:bg-amber-900/20 rounded-md border border-amber-100 dark:border-amber-900/30 flex items-start gap-4">
        <AlertTriangle className="w-5 h-5 text-amber-600 mt-0.5" />
        <div>
          <h4 className="text-xs font-bold text-amber-800 dark:text-amber-400 font-medium mb-1">Critical Action</h4>
          <p className="text-xs text-amber-700 dark:text-amber-500 leading-relaxed">
            Synchronizing will overwrite the existing visual ground truth. This action is recorded in the system audit log and cannot be undone.
          </p>
        </div>
      </div>
      <button 
        onClick={() => onAction({ old: oldBaseline, new: newBaseline })}
        disabled={disabled || !oldBaseline || !newBaseline}
        className="w-full py-4 bg-amber-600 text-white rounded-xl font-bold text-sm shadow-lg shadow-amber-600/20 hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
      >
        <RefreshCw className="w-4 h-4" /> Sync & Replace Baseline
      </button>
    </div>
  );
}

function RunComparisonForm({ onAction, disabled, baselineNames }: { onAction: (p: any) => void, disabled: boolean, baselineNames: string[] }) {
  const [baseline, setBaseline] = React.useState('');
  const [url, setUrl] = React.useState('');
  const [browser, setBrowser] = React.useState('Chrome');
  const [device, setDevice] = React.useState('Desktop');
  const [locale, setLocale] = React.useState('en-US');

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="space-y-6">
          <FormSelect label="Select Baseline" options={baselineNames} value={baseline} onChange={setBaseline} />
          <FormItem label="Website URL" placeholder="https://stage.example.com" value={url} onChange={setUrl} />
        </div>
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-4">
            <FormSelect label="Browser" options={['Chrome', 'Safari', 'Firefox']} value={browser} onChange={setBrowser} />
            <FormSelect label="Device" options={['Desktop', 'iPhone 13', 'Pixel 6']} value={device} onChange={setDevice} />
            <FormSelect label="Locale" options={['en-US', 'zh-CN', 'ms-MY']} value={locale} onChange={setLocale} />
          </div>
          <div className="flex items-end pt-6">
            <button 
              onClick={() => onAction({ name: baseline, url, browsers: [browser], devices: [device], locales: [locale] })}
              disabled={disabled || !baseline || !url}
              className="w-full py-4 bg-accent text-white rounded-xl font-bold text-sm shadow-lg shadow-accent/20 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
            >
              <Zap className="w-4 h-4" /> Execute Comparison
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function FormItem({ label, placeholder, value, onChange, isTextArea }: { label: string, placeholder: string, value: string, onChange: (v: string) => void, isTextArea?: boolean }) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold font-medium text-[var(--on-surface-variant)] px-1">{label}</label>
      {isTextArea ? (
        <textarea 
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all min-h-[120px] resize-none dark:text-slate-100"
        />
      ) : (
        <input 
          type="text"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all dark:text-slate-100"
        />
      )}
    </div>
  );
}

function FormSelect({ label, options, value, onChange }: { label: string, options: string[], value: string, onChange: (v: string) => void }) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold font-medium text-[var(--on-surface-variant)] px-1">{label}</label>
      <select 
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all cursor-pointer appearance-none dark:text-slate-100"
      >
        <option value="" disabled className="dark:bg-slate-900">Select...</option>
        {options.map(opt => <option key={opt} value={opt} className="dark:bg-slate-900">{opt}</option>)}
      </select>
    </div>
  );
}
