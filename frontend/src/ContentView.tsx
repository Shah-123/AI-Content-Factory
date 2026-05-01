import React, { useState } from 'react';
import {
  CheckCircle2, Clock, LayoutTemplate, Podcast, Film, Share2, Download,
  FileText, File, Code, FileJson, UploadCloud, ChevronRight, ListOrdered,
  RefreshCw, History, CheckCircle, Settings, Image as ImageIcon
} from 'lucide-react';
import { APIClient, Job } from './api';

type ViewState = 'chat' | 'content' | 'media';

export function ContentView({ navTo, currentJob, refreshJob }: { navTo: (v: ViewState) => void, currentJob: Job | null, refreshJob: () => void }) {
  const [triggering, setTriggering] = useState<Record<string, boolean>>({});

  const handleTrigger = async (task: string) => {
    if (!currentJob) return;
    setTriggering(p => ({ ...p, [task]: true }));
    try {
      if (task === 'qa') await APIClient.triggerQA(currentJob.id);
      if (task === 'podcast') { await APIClient.triggerPodcast(currentJob.id); navTo('media'); }
      if (task === 'video') { await APIClient.triggerVideo(currentJob.id); navTo('media'); }
      if (task === 'social') { await APIClient.triggerSocial(currentJob.id); navTo('media'); }
      if (task === 'images') { await APIClient.triggerImages(currentJob.id); navTo('media'); }
      refreshJob();
    } catch (e) { console.error(`Failed to trigger ${task}`); }
    setTriggering(p => ({ ...p, [task]: false }));
  };

  const DerivBtn = ({ task, icon, label, disabled }: { task: string; icon: React.ReactNode; label: string; disabled?: boolean }) => (
    <button onClick={() => handleTrigger(task)} disabled={triggering[task] || disabled}
      className="w-full flex items-center justify-between p-3.5 rounded-xl bg-base-850 border border-white/[0.05] hover:border-accent-500/30 hover:bg-base-800 transition-all group disabled:opacity-40 disabled:cursor-not-allowed">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-accent-glow flex items-center justify-center text-accent-400 group-hover:text-accent-300 transition-colors">
          {triggering[task] ? <RefreshCw className="w-4 h-4 animate-spin" /> : icon}
        </div>
        <span className="font-medium text-sm text-base-100">{label}</span>
      </div>
      <ChevronRight className="w-4 h-4 text-base-500 group-hover:text-accent-400 transition-colors" />
    </button>
  );

  return (
    <main className="flex-1 p-6 md:p-10 flex flex-col xl:flex-row gap-8 items-start relative overflow-y-auto">
      <div className="flex-1 w-full max-w-4xl mx-auto xl:mx-0">
        <div className="mb-6 flex items-center justify-between fade-in">
          <div className="flex items-center gap-2.5">
            <span className="px-2.5 py-1 rounded-lg bg-accent-glow text-accent-400 text-[11px] font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-accent-500/20">
              {currentJob?.status === 'completed' ? <CheckCircle2 className="w-3 h-3" /> : <Clock className="w-3 h-3" />}
              {currentJob?.status || 'Draft'}
            </span>
            {currentJob?.qa_score && (
              <span className="px-2.5 py-1 rounded-lg bg-signal-success-dim text-signal-success text-[11px] font-semibold uppercase tracking-wider border border-signal-success/20">
                QA: {currentJob.qa_score}/10
              </span>
            )}
            {currentJob?.blog_evaluator_score !== undefined && (
              <span className="px-2.5 py-1 rounded-lg bg-signal-info-dim text-signal-info text-[11px] font-semibold uppercase tracking-wider border border-signal-info/20">
                Eval: {currentJob.blog_evaluator_score}/10
              </span>
            )}
          </div>
          <button className="text-base-400 text-sm font-medium hover:text-accent-400 transition-colors flex items-center gap-1.5 px-3 py-1.5 rounded-xl hover:bg-white/[0.03]">
            <History className="w-4 h-4" /> Versions
          </button>
        </div>

        <article className="high-contrast-card rounded-2xl p-8 md:p-12 shadow-[0_20px_50px_rgba(0,0,0,0.3)] relative overflow-hidden bg-white text-slate-800">
          <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-amber-500 to-amber-600"></div>
          {currentJob ? (
            <>
              {currentJob.final_content ? (
                <div className="prose prose-slate max-w-none prose-headings:text-slate-900 prose-a:text-amber-600 hover:prose-a:text-amber-500 whitespace-pre-wrap"
                  dangerouslySetInnerHTML={{ __html: currentJob.final_content }} />
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
            </>
          ) : (
            <div className="flex flex-col items-center justify-center p-12 text-slate-500">
              <FileText className="w-12 h-12 mb-4 opacity-50" />
              <p>Select a job to view drafts.</p>
            </div>
          )}
        </article>
      </div>

      <aside className="w-full xl:w-80 flex-shrink-0 flex flex-col gap-6 xl:sticky xl:top-8 pb-12 stagger">
        <section className="glass-panel rounded-2xl p-5">
          <h3 className="text-base font-bold text-base-100 mb-1.5 flex items-center gap-2 tracking-tight">
            <LayoutTemplate className="w-5 h-5 text-accent-400" /> Generate Derivatives
          </h3>
          <p className="text-[13px] text-base-400 mb-5">Transform this document into new formats.</p>
          <div className="flex flex-col gap-2.5">
            <DerivBtn task="qa" icon={<ListOrdered className="w-4 h-4" />} label="Run QA Revision" />
            <DerivBtn task="images" icon={<ImageIcon className="w-4 h-4" />} label="Blog Images" />
            <DerivBtn task="podcast" icon={<Podcast className="w-4 h-4" />} label={currentJob?.podcast_file ? 'Podcast Generated' : 'Podcast Script'} disabled={!!currentJob?.podcast_file} />
            <DerivBtn task="video" icon={<Film className="w-4 h-4" />} label={currentJob?.video_file ? 'Video Generated' : 'Video Storyboard'} disabled={!!currentJob?.video_file} />
            <DerivBtn task="social" icon={<Share2 className="w-4 h-4" />} label={currentJob?.social_linkedin ? 'Social Generated' : 'Social Media'} disabled={!!currentJob?.social_linkedin} />
          </div>
        </section>

        <section className="glass-pill rounded-2xl p-5">
          <h3 className="text-base font-bold text-base-100 mb-4 flex items-center gap-2">
            <Download className="w-5 h-5 text-base-400" /> Export Options
          </h3>
          <div className="grid grid-cols-2 gap-2.5">
            {[{icon: <FileText className="w-4 h-4" />, l: 'PDF'}, {icon: <File className="w-4 h-4" />, l: 'Word'}, {icon: <Code className="w-4 h-4" />, l: 'HTML'}, {icon: <FileJson className="w-4 h-4" />, l: 'JSON'}].map(e => (
              <button key={e.l} className="py-2.5 px-3 rounded-xl bg-base-800 text-sm font-medium text-base-300 hover:text-base-100 hover:bg-base-750 transition-colors flex items-center justify-center gap-2 border border-white/[0.04]">
                {e.icon} {e.l}
              </button>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-white/[0.04]">
            <button className="w-full py-2.5 px-4 rounded-xl glass-panel text-accent-400 font-medium text-sm hover:bg-white/[0.04] transition-colors flex justify-center items-center gap-2">
              <UploadCloud className="w-4 h-4" /> Publish to CMS
            </button>
          </div>
        </section>
      </aside>
    </main>
  );
}
