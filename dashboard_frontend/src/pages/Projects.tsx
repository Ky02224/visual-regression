import React from 'react';
import { 
  Folder, 
  Plus, 
  MoreVertical, 
  Search, 
  Grid, 
  List, 
  Star,
  Clock,
  ExternalLink
} from 'lucide-react';
import { cn } from '../lib/utils';

const mockProjects = [
  { id: 1, name: 'Analytical Lens Core', domain: 'analytical-lens.io', baselines: 524, lastRun: '2 mins ago', favorite: true },
  { id: 2, name: 'Staging Environment', domain: 'staging.lens.io', baselines: 480, lastRun: '1 hour ago', favorite: false },
  { id: 3, name: 'Legacy Dashboard', domain: 'legacy.lens.io', baselines: 120, lastRun: '3 days ago', favorite: false },
  { id: 4, name: 'Mobile App API', domain: 'api.lens.io', baselines: 85, lastRun: '1 week ago', favorite: true },
];

export function Projects() {
  const [projects, setProjects] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        const runs = data.runs || [];
        const baselines = data.baselines || [];
        
        // Group runs by suite_name to represent "Projects"
        const grouped = runs.reduce((acc: any, run: any) => {
          const suite = run.suite_name || 'Manual Exploration';
          if (!acc[suite]) {
            acc[suite] = {
              name: suite,
              id: suite,
              domain: run.url ? new URL(run.url).hostname : 'localhost',
              runs: 0,
              baselines: baselines.filter((b: any) => b.name.includes(suite)).length,
              lastRun: run.run,
              favorite: false
            };
          }
          acc[suite].runs += 1;
          return acc;
        }, {});

        setProjects(Object.values(grouped));
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="p-20 text-center text-slate-400 font-bold uppercase tracking-widest animate-pulse">Loading visual environments...</div>;
  }

  return (
    <div className="p-10 max-w-7xl mx-auto">
      <header className="mb-10 flex justify-between items-end">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-2">Projects</h2>
          <p className="text-on-surface-variant dark:text-slate-400 font-medium">Manage multiple laboratory environments and visual testing scopes.</p>
        </div>
        <button className="signature-gradient text-white px-6 py-2.5 rounded-lg font-bold text-sm shadow-lg shadow-primary/20 flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98] transition-all">
          <Plus className="w-4 h-4" />
          Create Project
        </button>
      </header>

      <div className="bg-surface-container-lowest dark:bg-slate-900 rounded-2xl p-4 ghost-border dark:border-slate-800 mb-8 flex items-center justify-between tonal-shadow">
        <div className="flex items-center gap-4 flex-1">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant w-4 h-4" />
            <input 
              className="w-full bg-surface-container-low dark:bg-slate-950 border-none rounded-xl py-2 pl-10 pr-4 text-sm focus:ring-2 focus:ring-primary/20 outline-none dark:text-slate-100" 
              placeholder="Search projects..." 
              type="text"
            />
          </div>
          <div className="h-6 w-px bg-outline-variant/20" />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {projects.map(project => (
          <ProjectCard key={project.id} project={project} />
        ))}
        
        {projects.length === 0 && (
          <div className="col-span-full py-20 text-center border-2 border-dashed border-slate-200 dark:border-slate-800 rounded-3xl">
             <Folder className="w-12 h-12 text-slate-200 mx-auto mb-4" />
             <p className="text-slate-400 font-bold">No visual projects discovered yet.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function ProjectCard({ project }: { project: any, key?: string | number }) {
  return (
    <div className="bg-surface-container-lowest dark:bg-slate-900 rounded-2xl p-6 ghost-border dark:border-slate-800 hover:shadow-xl transition-all group tonal-shadow">
      <div className="flex justify-between items-start mb-6">
        <div className="w-12 h-12 rounded-xl bg-primary-container/30 dark:bg-blue-900/20 flex items-center justify-center text-primary dark:text-blue-400">
          <Folder className="w-6 h-6" />
        </div>
        <div className="flex gap-1">
          <button className={cn("p-2 rounded-lg transition-colors", project.favorite ? "text-amber-400" : "text-on-surface-variant dark:text-slate-400 hover:bg-surface-container-low dark:hover:bg-slate-800")}>
            <Star className="w-4 h-4" fill={project.favorite ? "currentColor" : "none"} />
          </button>
          <button className="p-2 rounded-lg text-on-surface-variant dark:text-slate-400 hover:bg-surface-container-low dark:hover:bg-slate-800 transition-colors">
            <MoreVertical className="w-4 h-4" />
          </button>
        </div>
      </div>
      
      <h4 className="text-xl font-bold text-on-surface dark:text-slate-100 mb-1 flex items-center gap-2">
        {project.name}
        <ExternalLink className="w-3 h-3 opacity-0 group-hover:opacity-100 transition-opacity" />
      </h4>
      <p className="text-xs text-on-surface-variant dark:text-slate-500 font-mono mb-6">{project.domain}</p>

      <div className="grid grid-cols-2 gap-4 pt-6 border-t border-outline-variant/10 dark:border-slate-800">
        <div>
          <p className="text-[10px] font-bold text-on-surface-variant dark:text-slate-500 uppercase tracking-widest mb-1">Baselines</p>
          <p className="text-lg font-bold text-on-surface dark:text-slate-100">{project.baselines}</p>
        </div>
        <div>
          <p className="text-[10px] font-bold text-on-surface-variant dark:text-slate-500 uppercase tracking-widest mb-1">Last Run</p>
          <div className="flex items-center gap-1.5 text-on-surface dark:text-slate-300 font-semibold text-sm">
            <Clock className="w-3 h-3 text-primary dark:text-blue-400" />
            {project.lastRun}
          </div>
        </div>
      </div>
    </div>
  );
}
