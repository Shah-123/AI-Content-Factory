import React, { useState, useEffect, useRef } from 'react';
import {
  Bot, Factory, LayoutDashboard, Settings, Plus,
  Bell, ListOrdered, PlusCircle, Send, Network, History, FileEdit,
  CheckCircle2, RefreshCw, Search, Menu, Sparkles
} from 'lucide-react';
import { APIClient, WebSocketClient, Job, AgentEvent, CreateJobParams } from './api';
import { ContentView } from './ContentView';

type ViewState = 'chat' | 'content';

export default function App() {
  const [view, setView] = useState<ViewState>('chat');
  const [jobs, setJobs] = useState<Job[]>([]);
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const wsClientRef = useRef<WebSocketClient>(new WebSocketClient());

  const navTo = (v: ViewState) => setView(v);

  const fetchJobsList = async () => {
    try { const fetchedJobs = await APIClient.fetchJobs(); setJobs(fetchedJobs); } catch (e) { console.error("Failed to fetch jobs:", e); }
  };

  useEffect(() => {
    fetchJobsList();
    const interval = setInterval(fetchJobsList, 15000);
    return () => { clearInterval(interval); wsClientRef.current.disconnect(); };
  }, []);

  const loadJob = async (jobId: string) => {
    try {
      const job = await APIClient.getJob(jobId);
      setCurrentJob(job);
      setEvents([]);
      const ws = wsClientRef.current;
      ws.disconnect();
      ws.connect(jobId, (event) => {
        setEvents(prev => [...prev, event]);
        if (event.status === 'completed' || event.status === 'error') {
          APIClient.getJob(jobId).then(setCurrentJob).catch(console.error);
        }
      });
    } catch (e) { console.error("Failed to load job:", e); }
  };

  const refreshCurrentJob = async (jobId: string) => {
    try { const job = await APIClient.getJob(jobId); setCurrentJob(job); } catch(e) { console.error("Failed to refresh:", e); }
  };

  const handleCreateJob = async (params: CreateJobParams) => {
    try {
      const newJob = await APIClient.createJob(params);
      setCurrentJob(newJob);
      setEvents([]);
      fetchJobsList();
      const ws = wsClientRef.current;
      ws.disconnect();
      ws.connect(newJob.id, (event) => {
        setEvents(prev => [...prev, event]);
        if (['completed','error','plan_ready','plan_revised','plan_approved'].includes(event.status)) {
          APIClient.getJob(newJob.id).then(setCurrentJob).catch(console.error);
        }
      });
    } catch (e) { console.error("Failed to create job:", e); }
  };

  const handleApprovePlan = async (jobId: string) => {
    try { await APIClient.approvePlan(jobId); refreshCurrentJob(jobId); } catch(e) { console.error("Approve failed:", e); }
  };

  const handleRevisePlan = async (jobId: string, feedback: string) => {
    try { await APIClient.revisePlan(jobId, feedback); refreshCurrentJob(jobId); } catch(e) { console.error("Revise failed:", e); }
  };

  return (
    <div className="min-h-dvh flex overflow-hidden antialiased relative noise-bg ambient-bg">
      <Sidebar view={view} navTo={navTo} jobs={jobs} currentJob={currentJob} loadJob={loadJob} />
      <div className="flex-1 md:ml-[260px] flex flex-col h-dvh relative">
        <TopNav view={view} />
        {view === 'chat' && <ChatView navTo={navTo} currentJob={currentJob} events={events} handleCreateJob={handleCreateJob} handleApprovePlan={handleApprovePlan} handleRevisePlan={handleRevisePlan} />}
        {view === 'content' && <ContentView navTo={navTo} currentJob={currentJob} refreshJob={() => currentJob && refreshCurrentJob(currentJob.id)} events={events} />}
      </div>
    </div>
  );
}

// ==========================================
// SIDEBAR
// ==========================================

function Sidebar({ view, navTo, jobs, currentJob, loadJob }: { view: ViewState, navTo: (v: ViewState) => void, jobs: Job[], currentJob: Job | null, loadJob: (id: string) => void }) {
  const navItems: { key: ViewState; icon: React.ReactNode; label: string }[] = [
    { key: 'chat', icon: <LayoutDashboard className="w-[18px] h-[18px]" />, label: 'Dashboard' },
    { key: 'content', icon: <FileEdit className="w-[18px] h-[18px]" />, label: 'Drafts' },
  ];

  return (
    <aside className="w-[260px] h-full fixed left-0 top-0 bg-base-900/80 backdrop-blur-2xl hidden md:flex flex-col z-50 overflow-y-auto border-r border-white/4">
      <div className="flex items-center gap-3 px-6 pt-7 pb-6">
        <div className="w-9 h-9 rounded-xl bg-linear-to-br from-accent-500 to-accent-600 flex items-center justify-center shadow-[0_2px_12px_rgba(245,158,11,0.3)]">
          <Sparkles className="text-base-950 w-4 h-4" />
        </div>
        <div>
          <h1 className="text-lg font-bold text-gradient-amber tracking-tight leading-tight">Synthetic Ether</h1>
          <p className="text-[11px] text-base-400 font-medium tracking-wide uppercase">Content Factory</p>
        </div>
      </div>

      <div className="px-5 mb-6">
        <button onClick={() => navTo('chat')} className="btn-primary w-full py-2.5 rounded-xl flex items-center justify-center gap-2 text-sm">
          <Plus className="w-4 h-4" /> New Job
        </button>
      </div>

      <nav className="flex flex-col gap-1 px-4 grow">
        <div className="text-[10px] font-semibold text-base-500 mb-2 uppercase tracking-[0.12em] px-2">Navigation</div>
        {navItems.map(item => (
          <button key={item.key} onClick={() => navTo(item.key)}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all duration-200 group relative ${view === item.key ? 'bg-accent-500/10 text-accent-400' : 'text-base-400 hover:text-base-200 hover:bg-white/3'}`}>
            {view === item.key && <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r-full bg-accent-500" />}
            {item.icon}
            <span className="text-sm font-medium">{item.label}</span>
          </button>
        ))}
        <div className="h-px bg-white/4 my-3 mx-2" />
        <button className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-base-500 hover:text-base-300 hover:bg-white/3 transition-all">
          <History className="w-[18px] h-[18px]" /> <span className="text-sm font-medium">History</span>
        </button>
        <button className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-base-500 hover:text-base-300 hover:bg-white/3 transition-all mt-auto">
          <Settings className="w-[18px] h-[18px]" /> <span className="text-sm font-medium">Settings</span>
        </button>
      </nav>

      <div className="px-4 pb-6 pt-4">
        <div className="flex justify-between items-center mb-3 px-2">
          <div className="text-[10px] font-semibold text-base-500 uppercase tracking-[0.12em]">Recent Jobs</div>
          <button onClick={() => window.location.reload()} className="text-base-500 hover:text-accent-400 transition-colors p-1 rounded-lg hover:bg-white/4" title="Refresh"><RefreshCw className="w-3 h-3" /></button>
        </div>
        <div className="flex flex-col gap-1.5 max-h-[30vh] overflow-y-auto stagger">
          {jobs.slice(0, 10).map((job) => (
            <button key={job.id} onClick={() => loadJob(job.id)}
              className={`w-full text-left rounded-xl px-3 py-2.5 text-sm flex justify-between items-center transition-all duration-200 ${currentJob?.id === job.id ? 'bg-accent-500/8 border border-accent-500/20 text-base-100' : 'text-base-400 hover:text-base-200 hover:bg-white/3 border border-transparent'}`}>
              <span className="truncate pr-3 text-[13px]">{job.topic}</span>
              <div className="shrink-0">
                {job.status === 'completed' && <span className="text-[10px] font-semibold text-signal-success bg-signal-success-dim px-1.5 py-0.5 rounded-md uppercase tracking-wider">Done</span>}
                {job.status === 'failed' && <span className="text-[10px] font-semibold text-signal-error bg-signal-error-dim px-1.5 py-0.5 rounded-md uppercase tracking-wider">Fail</span>}
                {job.status === 'running' && <div className="w-2 h-2 rounded-full bg-accent-500 status-pulse" />}
                {job.status === 'awaiting_approval' && <div className="w-2 h-2 rounded-full bg-signal-warning status-pulse" />}
                {job.status === 'pending' && <div className="w-2 h-2 rounded-full bg-base-500" />}
              </div>
            </button>
          ))}
          {jobs.length === 0 && <div className="text-xs text-base-500 px-2 py-4 text-center">No jobs yet. Create one above.</div>}
        </div>
      </div>
    </aside>
  );
}

// ==========================================
// TOP NAV
// ==========================================

function TopNav({ view }: { view: ViewState }) {
  return (
    <nav className="sticky top-0 w-full z-40 bg-base-950/60 backdrop-blur-xl flex justify-between items-center px-6 md:px-8 py-3 border-b border-white/4 h-14 shrink-0">
      <div className="flex items-center gap-4">
        <span className="text-lg font-bold text-gradient-amber tracking-tight block md:hidden">Synthetic Ether</span>
        {view === 'content' && (
          <div className="hidden md:flex gap-1 text-sm">
            <button className="px-3 py-1.5 rounded-lg text-accent-400 bg-accent-500/10 font-semibold text-[13px]">Studio</button>
            <button className="px-3 py-1.5 rounded-lg text-base-400 hover:text-base-200 hover:bg-white/3 transition-all text-[13px]">Library</button>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        {view === 'content' && (
          <div className="hidden md:flex relative group mr-2">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-base-500 group-focus-within:text-accent-400 transition-colors" />
            <input className="bg-base-800 border border-white/6 rounded-xl pl-9 pr-4 py-1.5 text-sm text-base-100 focus:outline-none focus:border-accent-500/40 transition-all w-56 placeholder:text-base-500" placeholder="Search content..." type="text" />
          </div>
        )}
        <button className="p-2 rounded-xl text-base-400 hover:text-accent-400 hover:bg-white/3 transition-all"><Bell className="w-[18px] h-[18px]" /></button>
        <button className="p-2 rounded-xl text-base-400 hover:text-accent-400 hover:bg-white/3 transition-all hidden md:flex"><Settings className="w-[18px] h-[18px]" /></button>
        <button className="md:hidden p-2 rounded-xl text-base-400"><Menu className="w-[18px] h-[18px]" /></button>
        <div className="w-8 h-8 rounded-xl bg-linear-to-br from-accent-600 to-accent-700 flex items-center justify-center ml-1 cursor-pointer text-[11px] font-bold text-base-950 shadow-[0_2px_8px_rgba(245,158,11,0.2)]">SE</div>
      </div>
    </nav>
  );
}

// ==========================================
// CHAT VIEW
// ==========================================

function ChatView({ navTo, currentJob, events, handleCreateJob, handleApprovePlan, handleRevisePlan }: {
  navTo: (v: ViewState) => void, currentJob: Job | null, events: AgentEvent[],
  handleCreateJob: (params: CreateJobParams) => void, handleApprovePlan: (jobId: string) => void, handleRevisePlan: (jobId: string, feedback: string) => void
}) {
  const [topicInput, setTopicInput] = useState('');
  const [tone, setTone] = useState('professional');
  const [sections, setSections] = useState(3);
  const [feedback, setFeedback] = useState('');

  const submitJob = () => {
    if (!topicInput.trim()) return;
    handleCreateJob({ topic: topicInput, tone, sections, generate_podcast: false, generate_video: false, generate_campaign: false });
    setTopicInput('');
  };

  const isAwaitingApproval = currentJob?.status === 'awaiting_approval';

  return (
    <main className="flex-1 flex flex-col p-6 md:p-8 relative overflow-hidden">
      <header className="mb-6 shrink-0 fade-in">
        <h2 className="text-3xl md:text-4xl font-bold tracking-tight text-base-50 mb-1.5">AI Content Factory</h2>
        <p className="text-base-400 text-sm flex items-center gap-2.5">
          <span className="font-mono text-[11px] text-base-500">Powered by LangGraph</span>
          {currentJob && currentJob.status !== 'completed' && currentJob.status !== 'failed' && (
            <span className="px-2 py-0.5 rounded-md bg-accent-glow text-accent-400 text-[11px] font-semibold border border-accent-500/20 flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-accent-500 status-pulse" /> Processing
            </span>
          )}
          {currentJob?.status === 'completed' && (
            <span className="px-2 py-0.5 rounded-md bg-signal-success-dim text-signal-success text-[11px] font-semibold border border-signal-success/20 flex items-center gap-1.5">
              <CheckCircle2 className="w-3 h-3" /> Completed
            </span>
          )}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto pr-2 md:pr-4 flex flex-col gap-5 pb-40 scroll-smooth stagger">
        {currentJob && (
          <div className="self-end max-w-2xl w-full">
            <div className="bg-linear-to-br from-accent-700 to-accent-600 p-5 rounded-2xl rounded-tr-sm text-base-950 shadow-lg shadow-accent-500/10">
              <p className="text-base font-medium">Write a blog on: {currentJob.topic}</p>
              <p className="text-sm opacity-70 mt-1">Tone: {currentJob.tone}</p>
            </div>
            <div className="text-right mt-1.5 text-[11px] text-base-500 font-medium">You</div>
          </div>
        )}

        {events.map((event, i) => (
          <div key={i} className="self-start max-w-3xl flex gap-3 w-full">
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 ${event.status === 'error' ? 'bg-signal-error-dim' : 'bg-base-800 border border-white/6'}`}>
              <Network className={`w-4 h-4 ${event.status === 'error' ? 'text-signal-error' : 'text-accent-400'}`} />
            </div>
            <div className="glass-panel p-4 rounded-2xl rounded-tl-sm flex-1">
              <div className="flex items-center gap-2 mb-1.5">
                <span className={`font-semibold text-sm ${event.status === 'error' ? 'text-signal-error' : 'text-accent-400'} capitalize`}>{event.agent_name}</span>
                <span className="text-[11px] text-base-500 font-mono">{new Date(event.timestamp * 1000).toLocaleTimeString()}</span>
              </div>
              <p className="text-base-200 text-sm flex items-center gap-2 leading-relaxed">
                {event.status === 'working' || event.status === 'started' ? <RefreshCw className="w-3.5 h-3.5 text-accent-400 animate-spin shrink-0" />
                 : event.status === 'error' ? <span className="text-signal-error font-bold text-xs">ERR</span>
                 : <Bot className="w-4 h-4 text-signal-success shrink-0" />}
                {event.message}
              </p>
            </div>
          </div>
        ))}

        {isAwaitingApproval && currentJob?.plan && (
          <div className="self-start max-w-3xl flex gap-3 w-full mt-2">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-signal-warning-dim">
              <Bot className="w-4 h-4 text-signal-warning" />
            </div>
            <div className="glass-panel p-6 rounded-2xl rounded-tl-sm flex-1 border border-signal-warning/20">
              <h3 className="text-lg font-bold text-signal-warning mb-1">Plan Ready for Approval</h3>
              <p className="text-sm text-base-300 mb-4">Review the outline below. Approve to proceed, or provide feedback.</p>
              <div className="bg-base-900 p-4 rounded-xl border border-white/4 mb-4">
                <h4 className="font-bold text-base-100 mb-2 text-sm">{currentJob.plan.blog_title}</h4>
                <ul className="list-none pl-0 text-sm text-base-300 space-y-2">
                  {currentJob.plan.tasks?.map((t: any) => (
                    <li key={t.id} className="flex items-start gap-2">
                      <span className="text-accent-500 mt-0.5 shrink-0">›</span>
                      <span><span className="font-medium text-base-100">{t.title}</span> — {t.goal}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="flex flex-col gap-3">
                <textarea className="w-full bg-base-800 border border-white/6 rounded-xl p-3 text-sm text-base-100 focus:outline-none focus:border-accent-500/40 resize-none h-20 placeholder:text-base-500"
                  placeholder="Enter feedback for revision (optional)..." value={feedback} onChange={e => setFeedback(e.target.value)} />
                <div className="flex gap-2 justify-end">
                  {feedback.trim().length > 0 && (
                    <button onClick={() => { handleRevisePlan(currentJob.id, feedback); setFeedback(''); }}
                      className="px-4 py-2 bg-base-700 hover:bg-base-600 text-base-200 rounded-xl text-sm font-semibold transition-colors border border-white/6">Revise Plan</button>
                  )}
                  <button onClick={() => handleApprovePlan(currentJob.id)}
                    className="px-5 py-2 bg-signal-success/20 hover:bg-signal-success/30 text-signal-success border border-signal-success/30 rounded-xl text-sm font-semibold transition-colors">Approve & Generate</button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {(!currentJob || currentJob.status === 'completed' || currentJob.status === 'failed') && (
        <div className="absolute bottom-6 left-6 md:left-8 right-6 md:right-8 z-30">
          <div className="glass-panel rounded-2xl p-4 flex flex-col gap-3 max-w-4xl mx-auto bg-base-900/90">
            <div className="flex gap-2 px-1 overflow-x-auto pb-1">
              {['professional', 'conversational', 'technical', 'educational'].map(t => (
                <button key={t} onClick={() => setTone(t)}
                  className={`px-3.5 py-1.5 rounded-lg text-xs whitespace-nowrap capitalize font-medium transition-all ${tone === t ? 'text-accent-400 bg-accent-500/10 border border-accent-500/20' : 'text-base-400 hover:text-base-200 border border-transparent hover:bg-white/3'}`}>{t}</button>
              ))}
              <div className="ml-auto items-center gap-2 text-xs text-base-400 bg-base-800 px-3 py-1.5 rounded-lg whitespace-nowrap hidden sm:flex border border-white/4">
                <ListOrdered className="w-3.5 h-3.5" />
                <select className="bg-transparent border-none outline-none focus:ring-0 text-base-200 cursor-pointer text-xs" value={sections} onChange={e => setSections(Number(e.target.value))}>
                  {[2,3,4,5,6].map(n => <option key={n} value={n}>{n} sections</option>)}
                </select>
              </div>
            </div>
            <div className="flex items-end gap-2 bg-base-800 rounded-xl p-2 border border-white/6 focus-within:border-accent-500/30 transition-colors">
              <button className="p-2.5 text-base-500 hover:text-accent-400 transition-colors hidden sm:block rounded-lg hover:bg-white/3">
                <PlusCircle className="w-5 h-5" />
              </button>
              <textarea className="flex-1 bg-transparent border-none text-base-100 focus:ring-0 resize-none py-2.5 px-2 placeholder-base-500 text-sm h-[44px] focus:outline-none leading-relaxed"
                placeholder="Enter a topic to generate a new blog..." value={topicInput} onChange={e => setTopicInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitJob(); } }} />
              <button onClick={submitJob} disabled={!topicInput.trim()}
                className={`btn-primary w-10 h-10 rounded-xl flex items-center justify-center shrink-0 group ${!topicInput.trim() ? 'opacity-40 cursor-not-allowed shadow-none! transform-none!' : ''}`}>
                <Send className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}