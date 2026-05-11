import { useState, useEffect, useRef } from 'react';
import { APIClient, WebSocketClient, Job, AgentEvent, CreateJobParams } from './api';
import { ContentView } from './ContentView';
import { ViewState } from './types';
import { Sidebar } from './components/Sidebar';
import { TopNav } from './components/TopNav';
import { ChatView } from './components/ChatView';

export default function App() {
  const [view, setView]               = useState<ViewState>('chat');
  const [jobs, setJobs]               = useState<Job[]>([]);
  const [currentJob, setCurrentJob]   = useState<Job | null>(null);
  const [events, setEvents]           = useState<AgentEvent[]>([]);
  const [topicError, setTopicError]   = useState<{ reason: string; category?: string; suggested_topic?: string } | null>(null);
  const wsClientRef                   = useRef<WebSocketClient>(new WebSocketClient());

  const navTo = (v: ViewState) => setView(v);

  const fetchJobsList = async () => {
    try {
      const fetched = await APIClient.fetchJobs();
      setJobs(fetched);
    } catch (e) {
      console.error('Failed to fetch jobs:', e);
    }
  };

  // Poll jobs every 15s and clean up the websocket on unmount.
  useEffect(() => {
    fetchJobsList();
    const interval = setInterval(fetchJobsList, 15000);
    return () => {
      clearInterval(interval);
      wsClientRef.current.disconnect();
    };
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
    } catch (e) {
      console.error('Failed to load job:', e);
    }
  };

  // Re-dial the WebSocket when a secondary task (video/podcast/social) is triggered
  // from ContentView after the main pipeline's WS has already closed. We clear the
  // events list so only the new task's events are displayed.
  const reconnectWS = (jobId: string) => {
    setEvents([]);
    const ws = wsClientRef.current;
    ws.disconnect();
    ws.connect(jobId, (event) => {
      setEvents(prev => {
        // De-dupe replayed events by (agent + message + ~timestamp).
        const isDupe = prev.some(
          e => e.agent_name === event.agent_name
            && e.message === event.message
            && Math.abs(e.timestamp - event.timestamp) < 0.01
        );
        if (isDupe) return prev;
        return [...prev, event];
      });
      if (event.agent_name === 'system' && (event.status === 'completed' || event.status === 'error')) {
        APIClient.getJob(jobId).then(setCurrentJob).catch(console.error);
      }
    });
  };

  const refreshCurrentJob = async (jobId: string) => {
    try {
      const job = await APIClient.getJob(jobId);
      setCurrentJob(job);
    } catch (e) {
      console.error('Failed to refresh:', e);
    }
  };

  const handleCreateJob = async (params: CreateJobParams) => {
    setTopicError(null);
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
    } catch (e: any) {
      if (e?.code === 'topic_rejected') {
        setTopicError({
          reason: e.reason || 'Topic was rejected.',
          category: e.category,
          suggested_topic: e.suggested_topic || '',
        });
      } else {
        console.error('Failed to create job:', e);
        setTopicError({ reason: 'Could not start the job. Please try again.' });
      }
    }
  };

  const handleApprovePlan = async (jobId: string) => {
    try { await APIClient.approvePlan(jobId); refreshCurrentJob(jobId); }
    catch(e) { console.error('Approve failed:', e); }
  };

  const handleRevisePlan = async (jobId: string, feedback: string) => {
    try { await APIClient.revisePlan(jobId, feedback); refreshCurrentJob(jobId); }
    catch(e) { console.error('Revise failed:', e); }
  };

  const handleUpdatePlan = async (jobId: string, plan: any) => {
    try { await APIClient.updatePlan(jobId, plan); refreshCurrentJob(jobId); }
    catch(e) { console.error('Update plan failed:', e); }
  };

  const startNewJob = () => {
    setCurrentJob(null);
    setEvents([]);
    setTopicError(null);
    navTo('chat');
  };

  return (
    <div className="min-h-dvh flex overflow-hidden antialiased relative noise-bg ambient-bg">
      <Sidebar
        view={view}
        navTo={navTo}
        jobs={jobs}
        currentJob={currentJob}
        loadJob={loadJob}
        startNewJob={startNewJob}
      />
      <div className="flex-1 md:ml-[260px] flex flex-col h-dvh relative">
        <TopNav view={view} />
        {view === 'chat' && (
          <ChatView
            navTo={navTo}
            currentJob={currentJob}
            events={events}
            topicError={topicError}
            clearTopicError={() => setTopicError(null)}
            handleCreateJob={handleCreateJob}
            handleApprovePlan={handleApprovePlan}
            handleRevisePlan={handleRevisePlan}
            handleUpdatePlan={handleUpdatePlan}
          />
        )}
        {view === 'content' && (
          <ContentView
            navTo={navTo}
            currentJob={currentJob}
            refreshJob={() => currentJob && refreshCurrentJob(currentJob.id)}
            events={events}
            reconnectWS={reconnectWS}
          />
        )}
      </div>
    </div>
  );
}
