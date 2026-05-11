import { useState, useEffect, useRef } from 'react';
import {
  ListOrdered, PlusCircle, Send, Network,
  CheckCircle2, RefreshCw, TrendingUp, ShieldAlert, X
} from 'lucide-react';
import { APIClient, Job, AgentEvent, CreateJobParams, UploadResult, SourceMode } from '../api';
import { ViewState } from '../types';
import { PlanEditor } from './PlanEditor';
import { UploadChip } from './UploadChip';

const ACCEPTED_UPLOAD_TYPES = '.pdf,.docx,.txt,.md';

interface ChatViewProps {
  navTo: (v: ViewState) => void;
  currentJob: Job | null;
  events: AgentEvent[];
  topicError?: { reason: string; category?: string; suggested_topic?: string } | null;
  clearTopicError?: () => void;
  handleCreateJob:    (params: CreateJobParams) => void;
  handleApprovePlan:  (jobId: string) => void;
  handleRevisePlan:   (jobId: string, feedback: string) => void;
  handleUpdatePlan:   (jobId: string, plan: any) => void;
}

export function ChatView({
  currentJob, events, topicError, clearTopicError,
  handleCreateJob, handleApprovePlan, handleRevisePlan, handleUpdatePlan,
}: ChatViewProps) {
  const [topicInput, setTopicInput] = useState('');
  const [tone, setTone]             = useState('professional');
  const [sections, setSections]     = useState(3);
  const [trending, setTrending]     = useState<string[]>([]);

  // Document upload state
  const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'ready' | 'error'>('idle');
  const [uploadName, setUploadName] = useState<string>('');
  const [uploadResult, setUploadResult] = useState<UploadResult | null>(null);
  const [uploadError, setUploadError] = useState<string>('');
  const [sourceMode, setSourceMode] = useState<SourceMode>('hybrid');
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Fetch trending topics once when the dashboard mounts so the empty state has quick-picks.
  useEffect(() => {
    APIClient.fetchTrending().then(setTrending).catch(() => setTrending([]));
  }, []);

  const clearUpload = () => {
    setUploadStatus('idle');
    setUploadName('');
    setUploadResult(null);
    setUploadError('');
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleFileSelected = async (file: File | undefined) => {
    if (!file) return;
    setUploadStatus('uploading');
    setUploadName(file.name);
    setUploadResult(null);
    setUploadError('');
    try {
      const result = await APIClient.uploadDocument(file);
      setUploadResult(result);
      setUploadStatus('ready');
      // If the user hasn't typed a topic yet, pre-fill the derived one.
      if (!topicInput.trim() && result.derived_topic) {
        setTopicInput(result.derived_topic);
      }
    } catch (e: any) {
      setUploadError(e?.message || 'Upload failed.');
      setUploadStatus('error');
    }
  };

  const submitJob = (overrideTopic?: string) => {
    // For auto_topic, fall back to the derived topic if the textarea is empty.
    let topic = (overrideTopic ?? topicInput).trim();
    if (!topic && sourceMode === 'auto_topic' && uploadResult?.derived_topic) {
      topic = uploadResult.derived_topic;
    }
    if (!topic) return;
    const upload_id = uploadStatus === 'ready' ? uploadResult?.upload_id : undefined;
    handleCreateJob({
      topic, tone, sections,
      generate_podcast: false, generate_video: false, generate_campaign: false,
      upload_id,
      source_mode: upload_id ? sourceMode : undefined,
    });
    setTopicInput('');
    clearUpload();
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
            <div className="aurora-bubble p-5 rounded-2xl rounded-tr-sm">
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
                {event.status === 'error'
                  ? <span className="text-signal-error font-bold text-xs">ERR</span>
                  : (event.status === 'working' || event.status === 'started')
                       && i === events.length - 1
                       && currentJob?.status !== 'completed'
                       && currentJob?.status !== 'failed'
                    ? <RefreshCw className="w-3.5 h-3.5 text-accent-400 animate-spin shrink-0" />
                    : <CheckCircle2 className="w-4 h-4 text-signal-success shrink-0" />}
                {event.message}
              </p>
            </div>
          </div>
        ))}

        {events.length === 0 && currentJob?.status === 'completed' && (
          <div className="self-start max-w-3xl flex gap-3 w-full">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 bg-base-800 border border-white/6">
              <Network className="w-4 h-4 text-accent-400" />
            </div>
            <div className="glass-panel p-4 rounded-2xl rounded-tl-sm flex-1">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="font-semibold text-sm text-accent-400 capitalize">system</span>
                {currentJob.completed_at && <span className="text-[11px] text-base-500 font-mono">{new Date(currentJob.completed_at).toLocaleTimeString()}</span>}
              </div>
              <p className="text-base-200 text-sm flex items-center gap-2 leading-relaxed">
                <CheckCircle2 className="w-4 h-4 text-signal-success shrink-0" />
                Historical job completed successfully.
              </p>
            </div>
          </div>
        )}

        {isAwaitingApproval && currentJob?.plan && (
          <PlanEditor
            plan={currentJob.plan}
            jobId={currentJob.id}
            onApprove={() => handleApprovePlan(currentJob.id)}
            onRevise={(fb) => handleRevisePlan(currentJob.id, fb)}
            onUpdatePlan={(plan) => handleUpdatePlan(currentJob.id, plan)}
          />
        )}
      </div>

      {(!currentJob || currentJob.status === 'completed' || currentJob.status === 'failed') && (
        <div className="absolute bottom-6 left-6 md:left-8 right-6 md:right-8 z-30">
          {topicError && (
            <div className="max-w-4xl mx-auto mb-3 fade-in">
              <div className="flex items-start gap-3 p-3.5 pr-2 rounded-xl border border-signal-error/30 bg-signal-error-dim text-signal-error">
                <ShieldAlert className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="flex-1 text-sm leading-relaxed">
                  <span className="font-semibold">Topic rejected.</span>{' '}
                  <span className="text-base-200">{topicError.reason}</span>
                  {topicError.suggested_topic && (
                    <button
                      onClick={() => {
                        setTopicInput(topicError.suggested_topic!);
                        clearTopicError?.();
                      }}
                      className="block mt-2 text-xs text-accent-300 hover:text-accent-200 underline underline-offset-2"
                    >
                      Try this instead: "{topicError.suggested_topic}"
                    </button>
                  )}
                </div>
                <button
                  onClick={() => clearTopicError?.()}
                  className="p-1.5 text-base-400 hover:text-base-100 rounded-md hover:bg-white/5 shrink-0"
                  aria-label="Dismiss"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          )}
          {/* Trending quick-picks: visible only on the truly-empty dashboard */}
          {!currentJob && events.length === 0 && trending.length > 0 && (
            <div className="max-w-4xl mx-auto mb-3 flex flex-wrap items-center gap-2 fade-in">
              <span className="flex items-center gap-1.5 text-[11px] font-semibold text-base-500 uppercase tracking-[0.12em] mr-1">
                <TrendingUp className="w-3.5 h-3.5 text-accent-300" />
                Trending
              </span>
              {trending.map((topic, i) => (
                <button
                  key={i}
                  onClick={() => submitJob(topic)}
                  className="px-3.5 py-1.5 rounded-full text-xs glass-pill text-base-200 hover:text-base-50 hover:border-accent-500/30 transition-all whitespace-nowrap"
                  title={`Generate a blog on: ${topic}`}
                >
                  {topic}
                </button>
              ))}
            </div>
          )}
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

            {uploadStatus !== 'idle' && (
              <UploadChip
                status={uploadStatus}
                filename={uploadName}
                result={uploadResult}
                errorMessage={uploadError}
                sourceMode={sourceMode}
                onSourceModeChange={setSourceMode}
                onClear={clearUpload}
              />
            )}

            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_UPLOAD_TYPES}
              className="hidden"
              onChange={e => { handleFileSelected(e.target.files?.[0]); }}
            />

            <div className="flex items-end gap-2 bg-base-800 rounded-xl p-2 border border-white/6 focus-within:border-accent-500/30 transition-colors">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploadStatus === 'uploading'}
                title="Attach a document (PDF, DOCX, TXT, MD)"
                className={`p-2.5 transition-colors hidden sm:block rounded-lg ${
                  uploadStatus === 'ready'
                    ? 'text-accent-400 bg-accent-500/10 hover:bg-accent-500/15'
                    : 'text-base-500 hover:text-accent-400 hover:bg-white/3'
                } ${uploadStatus === 'uploading' ? 'opacity-50 cursor-wait' : ''}`}
              >
                <PlusCircle className="w-5 h-5" />
              </button>
              <textarea
                className="flex-1 bg-transparent border-none text-base-100 focus:ring-0 resize-none py-2.5 px-2 placeholder-base-500 text-sm h-[44px] focus:outline-none leading-relaxed"
                placeholder={
                  uploadStatus === 'ready' && sourceMode === 'auto_topic'
                    ? (uploadResult?.derived_topic
                        ? `Auto-topic ready — press Send (or override: "${uploadResult.derived_topic}")`
                        : 'Auto-topic mode — enter or override the title...')
                    : 'Enter a topic to generate a new blog...'
                }
                value={topicInput}
                onChange={e => setTopicInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitJob(); } }}
              />
              <button
                onClick={() => submitJob()}
                disabled={
                  uploadStatus === 'uploading'
                  || (!topicInput.trim()
                      && !(sourceMode === 'auto_topic' && uploadStatus === 'ready' && !!uploadResult?.derived_topic))
                }
                className={`btn-primary w-10 h-10 rounded-xl flex items-center justify-center shrink-0 group ${
                  (uploadStatus === 'uploading'
                   || (!topicInput.trim()
                       && !(sourceMode === 'auto_topic' && uploadStatus === 'ready' && !!uploadResult?.derived_topic)))
                    ? 'opacity-40 cursor-not-allowed shadow-none! transform-none!'
                    : ''
                }`}
              >
                <Send className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
