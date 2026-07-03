import React from 'react';
import {
  LayoutDashboard, FileEdit, History, Settings, Plus, RefreshCw, Sparkles, Trash2
} from 'lucide-react';
import { motion } from 'motion/react';
import { Job } from '../api';
import { ViewState } from '../types';

interface SidebarProps {
  view: ViewState;
  navTo: (v: ViewState) => void;
  jobs: Job[];
  currentJob: Job | null;
  loadJob: (id: string) => void;
  startNewJob: () => void;
  onDeleteJob?: (id: string) => void;
}

export function Sidebar({ view, navTo, jobs, currentJob, loadJob, startNewJob, onDeleteJob }: SidebarProps) {
  const navItems: { key: ViewState; icon: React.ReactNode; label: string }[] = [
    { key: 'chat',    icon: <LayoutDashboard className="w-[18px] h-[18px]" />, label: 'Dashboard' },
    { key: 'content', icon: <FileEdit       className="w-[18px] h-[18px]" />, label: 'Studio' },
  ];

  return (
    <aside className="w-[260px] h-full fixed left-0 top-0 bg-base-900/80 backdrop-blur-2xl hidden md:flex flex-col z-50 overflow-y-auto border-r border-white/4">
      <div className="flex items-center gap-3 px-6 pt-7 pb-6">
        <div className="w-9 h-9 rounded-xl aurora-chip flex items-center justify-center">
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 20, repeat: Infinity, ease: 'linear' }}
          >
            <Sparkles className="text-base-950 w-4 h-4" />
          </motion.div>
        </div>
        <div>
          <h1 className="text-lg font-bold text-gradient-amber tracking-tight leading-tight">Synthetic Ether</h1>
          <p className="text-[11px] text-base-400 font-medium tracking-wide uppercase">Content Factory</p>
        </div>
      </div>

      <div className="px-5 mb-6">
        <motion.button
          onClick={startNewJob}
          className="btn-primary w-full py-2.5 rounded-xl flex items-center justify-center gap-2 text-sm"
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          <Plus className="w-4 h-4" /> New Job
        </motion.button>
      </div>

      <nav className="flex flex-col gap-1 px-4 grow">
        <div className="text-[10px] font-semibold text-base-500 mb-2 uppercase tracking-[0.12em] px-2">Navigation</div>
        {navItems.map(item => (
          <button key={item.key} onClick={() => navTo(item.key)}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group relative sidebar-glow ${view === item.key ? 'bg-accent-500/10 text-accent-400' : 'text-base-400 hover:text-base-200'}`}>
            {view === item.key && (
              <motion.div
                layoutId="nav-active-indicator"
                className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-500"
                transition={{ type: 'spring', stiffness: 350, damping: 30 }}
              />
            )}
            {item.icon}
            <span className="text-sm font-medium">{item.label}</span>
          </button>
        ))}
        <div className="h-px bg-white/4 my-3 mx-2" />
        <button className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-base-500 hover:text-base-300 hover:bg-white/3 transition-all sidebar-glow">
          <History className="w-[18px] h-[18px]" /> <span className="text-sm font-medium">History</span>
        </button>
        <button className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-base-500 hover:text-base-300 hover:bg-white/3 transition-all mt-auto sidebar-glow">
          <Settings className="w-[18px] h-[18px]" /> <span className="text-sm font-medium">Settings</span>
        </button>
      </nav>

      <div className="px-4 pb-6 pt-4">
        <div className="flex justify-between items-center mb-3 px-2">
          <div className="text-[10px] font-semibold text-base-500 uppercase tracking-[0.12em]">Recent Jobs</div>
          <button onClick={() => window.location.reload()} className="text-base-500 hover:text-accent-400 transition-colors p-1 rounded-lg hover:bg-white/4" title="Refresh"><RefreshCw className="w-3 h-3" /></button>
        </div>
        <div className="flex flex-col gap-1.5 max-h-[30vh] overflow-y-auto">
          {jobs.slice(0, 10).map((job, i) => (
            <motion.div
              key={job.id}
              className="relative group w-full"
              initial={{ opacity: 0, x: -12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04, duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            >
              <button onClick={() => loadJob(job.id)}
                className={`w-full text-left rounded-xl pl-3 pr-8 py-2.5 text-sm flex justify-between items-center transition-all duration-200 sidebar-glow ${currentJob?.id === job.id ? 'bg-accent-500/8 border border-accent-500/20 text-base-100' : 'text-base-400 hover:text-base-200 border border-transparent'}`}>
                <span className="truncate pr-3 text-[13px]">{job.topic}</span>
                <div className="shrink-0 group-hover:opacity-0 transition-opacity">
                  {job.status === 'completed'         && (
                    <motion.span
                      initial={{ scale: 0.5 }}
                      animate={{ scale: 1 }}
                      className="text-[10px] font-semibold text-signal-success bg-signal-success-dim px-1.5 py-0.5 rounded-md uppercase tracking-wider inline-block"
                    >Done</motion.span>
                  )}
                  {job.status === 'failed'            && <span className="text-[10px] font-semibold text-signal-error   bg-signal-error-dim   px-1.5 py-0.5 rounded-md uppercase tracking-wider">Fail</span>}
                  {job.status === 'running'           && <div className="w-2 h-2 rounded-full bg-accent-500     status-pulse" />}
                  {job.status === 'awaiting_approval' && <div className="w-2 h-2 rounded-full bg-signal-warning status-pulse" />}
                  {job.status === 'pending'           && <div className="w-2 h-2 rounded-full bg-base-500" />}
                </div>
              </button>
              {onDeleteJob && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteJob(job.id);
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 text-base-500 hover:text-signal-error transition-opacity duration-200 p-1.5 rounded-lg hover:bg-white/4"
                  title="Delete job"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </motion.div>
          ))}
          {jobs.length === 0 && <div className="text-xs text-base-500 px-2 py-4 text-center">No jobs yet. Create one above.</div>}
        </div>
      </div>
    </aside>
  );
}
