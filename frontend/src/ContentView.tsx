import React, { useState, useEffect, useRef } from 'react';
import {
  CheckCircle2, Clock, Podcast, Film, Share2, Download,
  FileText, History, Settings, Image as ImageIcon,
  Play, Volume2, Copy, RefreshCw, LayoutTemplate, Bot
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { APIClient, Job, AgentEvent } from './api';

type ViewState = 'chat' | 'content';
type TabState = 'blog' | 'video' | 'podcast' | 'images' | 'social';

export function ContentView({ navTo, currentJob, refreshJob, events = [], reconnectWS }: { navTo: (v: ViewState) => void, currentJob: Job | null, refreshJob: () => void, events?: AgentEvent[], reconnectWS?: (jobId: string) => void }) {
  const [activeTab, setActiveTab] = useState<TabState>('blog');
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-clear triggering flags when generated data appears in the job
  useEffect(() => {
    if (!currentJob) return;
    setTriggering(prev => {
      const next = { ...prev };
      let changed = false;
      if (prev.social && (currentJob.social_linkedin || currentJob.social_twitter)) { next.social = false; changed = true; }
      if (prev.video && currentJob.video_file) { next.video = false; changed = true; }
      if (prev.podcast && currentJob.podcast_file) { next.podcast = false; changed = true; }
      if (prev.qa && currentJob.qa_score != null) { next.qa = false; changed = true; }
      return changed ? next : prev;
    });
  }, [currentJob]);

  // Stop polling when no tasks are active
  useEffect(() => {
    const anyActive = Object.values(triggering).some(v => v);
    if (!anyActive && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [triggering]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, []);

  const handleTrigger = async (task: string) => {
    if (!currentJob) return;
    setTriggering(p => ({ ...p, [task]: true }));
    try {
      // Re-connect the WebSocket so secondary-task events stream back live.
      // The main pipeline WS closes itself on system:completed, so we must re-dial.
      if (reconnectWS) {
        reconnectWS(currentJob.id);
      }
      if (task === 'qa') await APIClient.triggerQA(currentJob.id);
      if (task === 'podcast') await APIClient.triggerPodcast(currentJob.id);
      if (task === 'video') await APIClient.triggerVideo(currentJob.id);
      if (task === 'social') await APIClient.triggerSocial(currentJob.id);
      if (task === 'images') await APIClient.triggerImages(currentJob.id);
      // Start polling to detect when the background task completes
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(() => { refreshJob(); }, 3000);
      // Safety: stop polling after 5 minutes
      const safetyTimeout = setTimeout(() => {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
        setTriggering(p => ({ ...p, [task]: false }));
      }, 300000);
    } catch (e) {
      console.error(`Failed to trigger ${task}`);
      setTriggering(p => ({ ...p, [task]: false }));
    }
  };

  if (!currentJob) {
    return (
      <main className="flex-1 p-6 md:p-10 flex flex-col items-center justify-center text-slate-500">
        <FileText className="w-12 h-12 mb-4 opacity-50" />
        <p>Select a job to view drafts.</p>
      </main>
    );
  }

  return (
    <main className="flex-1 p-6 md:p-10 flex flex-col relative overflow-y-auto w-full max-w-6xl mx-auto">
      
      {/* Header and Tabs */}
      <div className="mb-8 fade-in">
        <div className="flex flex-col md:flex-row md:items-center justify-between mb-6 gap-4">
           <h2 className="text-2xl font-bold text-base-50 tracking-tight line-clamp-1">Studio: {currentJob.topic}</h2>
           <div className="flex items-center gap-2.5 shrink-0">
             <span className="px-2.5 py-1 rounded-lg bg-accent-glow text-accent-400 text-[11px] font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-accent-500/20">
               {currentJob?.status === 'completed' ? <CheckCircle2 className="w-3 h-3" /> : <Clock className="w-3 h-3" />}
               {currentJob?.status || 'Draft'}
             </span>
             <button className="text-base-400 text-sm font-medium hover:text-accent-400 transition-colors flex items-center gap-1.5 px-3 py-1.5 rounded-xl hover:bg-white/3">
               <History className="w-4 h-4" /> Versions
             </button>
           </div>
        </div>

        <div className="flex gap-2 text-sm font-medium overflow-x-auto pb-2 border-b border-white/4">
          <TabButton id="blog" icon={<FileText className="w-4 h-4"/>} label="Blog" activeTab={activeTab} setActiveTab={setActiveTab} />
          <TabButton id="video" icon={<Film className="w-4 h-4"/>} label="Video" activeTab={activeTab} setActiveTab={setActiveTab} />
          <TabButton id="podcast" icon={<Podcast className="w-4 h-4"/>} label="Podcast" activeTab={activeTab} setActiveTab={setActiveTab} />
          <TabButton id="social" icon={<Share2 className="w-4 h-4"/>} label="Social Media" activeTab={activeTab} setActiveTab={setActiveTab} />
          <TabButton id="images" icon={<ImageIcon className="w-4 h-4"/>} label="Images" activeTab={activeTab} setActiveTab={setActiveTab} />
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1">
        
        {/* BLOG TAB */}
        {activeTab === 'blog' && (
          <article className="high-contrast-card rounded-2xl p-8 md:p-12 shadow-[0_20px_50px_rgba(0,0,0,0.3)] relative overflow-hidden bg-white text-slate-800 animate-in fade-in duration-500">
            <div className="absolute top-0 left-0 w-full h-1 bg-linear-to-r from-amber-500 to-amber-600"></div>
            {currentJob.final_content ? (
              <div className="prose prose-slate max-w-none prose-headings:text-slate-900 prose-a:text-amber-600 hover:prose-a:text-amber-500">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {currentJob.final_content}
                </ReactMarkdown>
              </div>
            ) : currentJob.status === 'running' || currentJob.status === 'awaiting_approval' || currentJob.status === 'pending' ? (
              <div className="flex flex-col items-center justify-center p-12 text-slate-500 space-y-4">
                <div className="w-10 h-10 border-4 border-amber-200 border-t-amber-500 rounded-full animate-spin"></div>
                <p className="font-semibold text-slate-600">Agents are at work...</p>
                <p className="text-sm">Head back to the Dashboard to see live updates.</p>
              </div>
            ) : currentJob.status === 'failed' ? (
              <div className="flex flex-col items-center justify-center p-12 text-red-500 space-y-4">
                <Settings className="w-12 h-12 opacity-50" />
                <p className="font-bold">Generation failed</p>
                <p className="text-sm opacity-80">{currentJob.error_message || "An unknown error occurred."}</p>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center p-12 text-slate-500">
                <Clock className="w-12 h-12 mb-4 opacity-50" />
                <p>Content not available for this job.</p>
              </div>
            )}
          </article>
        )}

        {/* VIDEO TAB */}
        {activeTab === 'video' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            {currentJob.video_file ? (
              <div className="glass-panel p-6 rounded-2xl">
                 <div className="flex justify-between items-center mb-4">
                   <h3 className="text-xl font-bold text-base-50 flex items-center gap-2"><Film className="w-5 h-5 text-accent-400" /> Synthetic Video</h3>
                   <a href={APIClient.getFileUrl(currentJob.id, currentJob.video_file)} download target="_blank" rel="noreferrer"
                     className="btn-primary px-4 py-2 rounded-xl text-sm font-semibold flex items-center gap-2">
                     <Download className="w-4 h-4" /> Download MP4
                   </a>
                 </div>
                 <div className="bg-black rounded-xl overflow-hidden aspect-video border border-white/6 w-full max-w-4xl mx-auto">
                   <video src={APIClient.getFileUrl(currentJob.id, currentJob.video_file)} controls className="w-full h-full object-contain"></video>
                 </div>
              </div>
            ) : triggering['video'] || (events.some(e => e.agent_name === 'video' && e.status !== 'completed' && e.status !== 'error')) ? (
              <LoadingState title="Generating Video..." description="Our AI is crafting a storyboard, generating voiceovers, and compiling your video." agentEvents={events.filter(e => e.agent_name === 'video')} />
            ) : (
              <EmptyState 
                icon={<Film className="w-12 h-12" />} 
                title="Create a Video from your Blog" 
                description="Automatically transform this blog post into an engaging synthetic video with AI voiceover and animated visuals."
                onGenerate={() => handleTrigger('video')}
              />
            )}
          </div>
        )}

        {/* PODCAST TAB */}
        {activeTab === 'podcast' && (
           <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
             {currentJob.podcast_file ? (
               <div className="glass-panel p-6 rounded-2xl relative overflow-hidden group max-w-4xl mx-auto">
                  <div className="absolute -top-10 -right-10 w-40 h-40 bg-accent-500/5 rounded-full blur-3xl group-hover:bg-accent-500/10 transition-all duration-700"></div>
                  <div className="flex justify-between items-center mb-6 relative z-10">
                    <h3 className="text-xl font-bold text-base-50 flex items-center gap-2"><Podcast className="w-5 h-5 text-accent-400" /> Audio Podcast</h3>
                    <a href={APIClient.getFileUrl(currentJob.id, currentJob.podcast_file)} download target="_blank" rel="noreferrer"
                      className="btn-primary px-4 py-2 rounded-xl text-sm font-semibold flex items-center gap-2">
                      <Download className="w-4 h-4" /> Download MP3
                    </a>
                  </div>
                  <div className="bg-base-900 border border-white/4 rounded-xl p-6 relative z-10">
                    <div className="flex items-center gap-4 mb-4">
                      <div className="w-12 h-12 rounded-full bg-accent-500/20 flex items-center justify-center shrink-0">
                        <Volume2 className="w-6 h-6 text-accent-400" />
                      </div>
                      <div>
                        <h4 className="font-semibold text-base-100">{currentJob.topic}</h4>
                        <p className="text-xs text-base-400">AI Hosted Podcast</p>
                      </div>
                    </div>
                    <audio controls className="w-full accent-accent-500"><source src={APIClient.getFileUrl(currentJob.id, currentJob.podcast_file)} type="audio/mpeg" /></audio>
                  </div>
               </div>
             ) : triggering['podcast'] || (events.some(e => e.agent_name === 'podcast_generator' && e.status !== 'completed' && e.status !== 'error')) ? (
                <LoadingState title="Generating Podcast..." description="Our AI hosts are warming up their mics and preparing the script." agentEvents={events.filter(e => e.agent_name === 'podcast_generator')} />
             ) : (
                <EmptyState 
                  icon={<Podcast className="w-12 h-12" />} 
                  title="Generate a Podcast" 
                  description="Convert your written content into an engaging conversational audio podcast."
                  onGenerate={() => handleTrigger('podcast')}
                />
             )}
           </div>
        )}

        {/* SOCIAL TAB */}
        {activeTab === 'social' && (
           <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
             {currentJob.social_linkedin ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="glass-panel p-6 rounded-2xl flex flex-col h-full">
                    <div className="flex items-center justify-between mb-4">
                       <div className="flex items-center gap-2 text-sm font-semibold text-base-100">
                         <svg className="w-5 h-5 fill-current text-[#0a66c2]" viewBox="0 0 24 24"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"></path></svg>
                         LinkedIn Post
                       </div>
                       <button onClick={() => navigator.clipboard.writeText(currentJob.social_linkedin!)} className="text-base-400 hover:text-accent-400 transition-colors p-2 rounded-lg hover:bg-white/5" title="Copy to clipboard"><Copy className="w-4 h-4"/></button>
                    </div>
                    <div className="bg-base-900 rounded-xl p-5 border border-white/5 flex-1">
                      <p className="text-sm text-base-300 leading-relaxed whitespace-pre-wrap">{currentJob.social_linkedin}</p>
                    </div>
                  </div>
                  
                  <div className="glass-panel p-6 rounded-2xl flex flex-col h-full">
                    <div className="flex items-center justify-between mb-4">
                       <div className="flex items-center gap-2 text-sm font-semibold text-base-100">
                         <svg className="w-5 h-5 fill-current text-base-200" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.008 4.09H5.078z"></path></svg>
                         X / Twitter Thread
                       </div>
                       <button onClick={() => navigator.clipboard.writeText(currentJob.social_twitter!)} className="text-base-400 hover:text-accent-400 transition-colors p-2 rounded-lg hover:bg-white/5" title="Copy to clipboard"><Copy className="w-4 h-4"/></button>
                    </div>
                    <div className="bg-base-900 rounded-xl p-5 border border-white/5 flex-1">
                      <p className="text-sm text-base-300 leading-relaxed whitespace-pre-wrap">{currentJob.social_twitter}</p>
                    </div>
                  </div>
                </div>
             ) : triggering['social'] || (events.some(e => e.agent_name === 'campaign_generator' && e.status !== 'completed' && e.status !== 'error')) ? (
                <LoadingState title="Generating Campaign..." description="Drafting optimized posts for your social channels." agentEvents={events.filter(e => e.agent_name === 'campaign_generator')} />
             ) : (
                <EmptyState 
                  icon={<Share2 className="w-12 h-12" />} 
                  title="Generate Social Media Campaign" 
                  description="Automatically write engaging LinkedIn posts and X threads optimized for virality and reach."
                  onGenerate={() => handleTrigger('social')}
                />
             )}
           </div>
        )}

        {/* IMAGES TAB */}
        {activeTab === 'images' && (
           <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
              <div className="glass-panel p-12 rounded-2xl text-center max-w-2xl mx-auto flex flex-col items-center justify-center min-h-[400px]">
                <div className="w-20 h-20 bg-accent-500/10 rounded-full flex items-center justify-center mb-6">
                  <ImageIcon className="w-10 h-10 text-accent-400" />
                </div>
                <h3 className="text-2xl font-bold text-base-50 mb-3">Blog Images</h3>
                <p className="text-base-400 mb-8 max-w-md">Images are generated automatically when a blog is created. If you requested images, they will appear embedded directly inside the Blog tab content.</p>
                <button onClick={() => setActiveTab('blog')} className="btn-primary px-6 py-3 rounded-xl font-semibold shadow-[0_0_20px_rgba(245,158,11,0.2)] hover:shadow-[0_0_30px_rgba(245,158,11,0.3)] transition-all">
                  Go back to Blog
                </button>
              </div>
           </div>
        )}

      </div>
    </main>
  );
}

function TabButton({ id, icon, label, activeTab, setActiveTab }: { id: TabState, icon: React.ReactNode, label: string, activeTab: TabState, setActiveTab: (t: TabState) => void }) {
  const active = activeTab === id;
  return (
    <button onClick={() => setActiveTab(id)} 
      className={`px-4 py-2.5 rounded-xl transition-all flex items-center gap-2 whitespace-nowrap
      ${active ? 'bg-accent-500/10 text-accent-400 border border-accent-500/20 shadow-sm' : 'text-base-400 hover:text-base-200 hover:bg-white/3 border border-transparent'}`}>
      {icon} {label}
    </button>
  );
}

function EmptyState({ icon, title, description, onGenerate }: { icon: React.ReactNode, title: string, description: string, onGenerate: () => void }) {
  return (
    <div className="glass-panel p-12 rounded-2xl flex flex-col items-center justify-center text-center min-h-[400px] border border-white/4 relative overflow-hidden group max-w-3xl mx-auto">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] bg-accent-500/5 rounded-full blur-3xl group-hover:bg-accent-500/10 transition-all duration-700"></div>
      
      <div className="relative z-10 w-24 h-24 bg-base-900 rounded-full flex items-center justify-center mb-6 shadow-xl border border-white/6 text-accent-400 group-hover:scale-105 transition-transform duration-500">
        {icon}
      </div>
      <h3 className="text-2xl font-bold text-base-50 mb-3">{title}</h3>
      <p className="text-base-400 mb-8 max-w-md text-sm leading-relaxed">{description}</p>
      
      <button onClick={onGenerate} className="btn-primary px-8 py-3.5 rounded-xl font-bold shadow-[0_0_20px_rgba(245,158,11,0.2)] hover:shadow-[0_0_30px_rgba(245,158,11,0.4)] hover:-translate-y-1 transition-all flex items-center gap-2 z-10">
        <LayoutTemplate className="w-5 h-5" /> Generate Now
      </button>
    </div>
  );
}

function LoadingState({ title, description, agentEvents = [] }: { title: string, description: string, agentEvents?: AgentEvent[] }) {
  // Sort events by timestamp just in case
  const sortedEvents = [...agentEvents].sort((a, b) => a.timestamp - b.timestamp);
  
  return (
    <div className="glass-panel p-12 rounded-2xl flex flex-col items-center justify-center text-center min-h-[400px] border border-white/4 max-w-3xl mx-auto overflow-hidden relative">
      {/* Background Glow */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full h-1 bg-linear-to-r from-transparent via-accent-500/20 to-transparent"></div>
      
      <div className="relative mb-10 group">
        <div className="absolute inset-0 bg-accent-500/20 rounded-full blur-2xl group-hover:bg-accent-500/30 transition-all duration-700"></div>
        <div className="relative w-20 h-20 flex items-center justify-center">
           {/* Outer Ring */}
           <div className="absolute inset-0 border-4 border-white/5 rounded-full"></div>
           {/* Spinning Loader */}
           <div className="absolute inset-0 border-4 border-transparent border-t-accent-500 border-r-accent-500 rounded-full animate-spin shadow-[0_0_15px_rgba(245,158,11,0.4)]"></div>
           <Bot className="w-8 h-8 text-accent-400 relative z-10 animate-pulse" />
        </div>
      </div>
      
      <h3 className="text-2xl font-bold text-base-50 mb-3 tracking-tight">{title}</h3>
      <p className="text-base-400 text-sm max-w-md leading-relaxed mb-10">{description}</p>
      
      {sortedEvents.length > 0 && (
        <div className="w-full max-w-lg text-left bg-base-900/40 backdrop-blur-sm rounded-2xl p-6 border border-white/4 shadow-2xl relative overflow-hidden">
          <div className="absolute top-0 left-0 w-1 h-full bg-accent-500/10"></div>
          
          <div className="flex items-center justify-between mb-5 px-1">
            <div className="text-[10px] font-bold text-base-500 uppercase tracking-[0.2em]">Neural Pipeline Status</div>
            <div className="flex gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-accent-500 animate-pulse"></div>
              <div className="w-1.5 h-1.5 rounded-full bg-accent-500/40"></div>
              <div className="w-1.5 h-1.5 rounded-full bg-accent-500/20"></div>
            </div>
          </div>
          
          <div className="space-y-4">
            {sortedEvents.map((event, i) => {
              const isLast = i === sortedEvents.length - 1;
              const isError = event.status === 'error';
              const isExplicitlyCompleted = event.status === 'completed';
              
              // Logic: 
              // 1. If it's NOT the last event, it's considered "done" (show tick)
              // 2. If it's the last event, show spinning if it's 'working'/'started', else show tick if 'completed'
              const showTick = !isLast || isExplicitlyCompleted;
              const showLoading = isLast && !isExplicitlyCompleted && !isError;
              
              return (
                <div key={i} className="flex items-start gap-4 group animate-in fade-in slide-in-from-bottom-3 duration-500" style={{ animationDelay: `${i * 100}ms` }}>
                  <div className="mt-0.5 shrink-0 relative">
                    {/* Vertical line connector */}
                    {!isLast && <div className="absolute top-5 left-1/2 -translate-x-1/2 w-px h-4 bg-white/10 group-hover:bg-accent-500/30 transition-colors"></div>}
                    
                    {isError ? (
                      <div className="w-5 h-5 rounded-full bg-signal-error-dim flex items-center justify-center border border-signal-error/30">
                        <div className="w-2 h-2 rounded-full bg-signal-error shadow-[0_0_8px_rgba(251,113,133,0.5)]"></div>
                      </div>
                    ) : showTick ? (
                      <div className="flex items-center justify-center w-5 h-5 rounded-full bg-signal-success/10 border border-signal-success/20">
                         <CheckCircle2 className="w-3.5 h-3.5 text-signal-success" />
                      </div>
                    ) : (
                      <div className="relative w-5 h-5 flex items-center justify-center">
                        <RefreshCw className="w-3.5 h-3.5 text-accent-400 animate-spin" />
                        <div className="absolute inset-0 bg-accent-500/20 rounded-full blur-md animate-pulse"></div>
                      </div>
                    )}
                  </div>
                  
                  <div className="flex-1 pb-1">
                    <p className={`text-[13px] font-medium transition-colors duration-300 ${
                      isError ? 'text-signal-error' : showTick ? 'text-base-300' : 'text-base-100'
                    }`}>
                      {event.message}
                    </p>
                    {showLoading && (
                      <div className="mt-2 w-full h-[2px] bg-white/5 rounded-full overflow-hidden">
                        <div className="h-full bg-accent-500 progress-bar-animated w-[40%] rounded-full"></div>
                      </div>
                    )}
                  </div>
                  
                  <span className="text-[9px] font-mono text-base-600 mt-1 uppercase">
                    {new Date(event.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
