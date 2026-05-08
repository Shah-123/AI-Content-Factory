const API_BASE_URL = 'http://localhost:8000';
const WS_BASE_URL = 'ws://localhost:8000';

export interface CreateJobParams {
  topic: string;
  tone?: string;
  sections?: number;
  generate_podcast?: boolean;
  generate_video?: boolean;
  generate_campaign?: boolean;
}

export interface Job {
  id: string;
  topic: string;
  tone: string;
  sections: number;
  status: 'pending' | 'running' | 'awaiting_approval' | 'completed' | 'failed';
  created_at: string;
  completed_at?: string;
  blog_folder?: string;
  qa_score?: number;
  qa_verdict?: string;
  blog_evaluator_score?: number;
  blog_file?: string;
  blog_html_file?: string;
  podcast_file?: string;
  video_file?: string;
  plan?: any;
  error_message?: string;
  word_count?: number;
  final_content?: string;
  social_linkedin?: string;
  social_twitter?: string;
}

export interface AgentEvent {
  job_id: string;
  agent_name: string;
  status: 'started' | 'working' | 'completed' | 'error' | 'plan_ready' | 'plan_revised' | 'plan_approved';
  message: string;
  timestamp: number;
  metrics?: Record<string, any>;
  type?: string; // used for internal ping/keepalive
}

export class APIClient {
  static async fetchJobs(): Promise<Job[]> {
    const res = await fetch(`${API_BASE_URL}/api/jobs`);
    if (!res.ok) throw new Error('Failed to fetch jobs');
    return res.json();
  }

  static async createJob(params: CreateJobParams): Promise<Job> {
    const res = await fetch(`${API_BASE_URL}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error('Failed to create job');
    return res.json();
  }

  static async getJob(id: string): Promise<Job> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}`);
    if (!res.ok) throw new Error('Failed to get job');
    return res.json();
  }

  static async approvePlan(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/approve-plan`);
    if (!res.ok) throw new Error('Failed to approve plan');
  }

  static async revisePlan(id: string, feedback: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/revise-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback }),
    });
    if (!res.ok) throw new Error('Failed to revise plan');
  }

  static async updatePlan(id: string, plan: {
    blog_title: string;
    tone: string;
    audience: string;
    tasks: Array<{ title: string; goal: string; bullets: string[]; target_words: number; tags: string[] }>;
  }): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/update-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(plan),
    });
    if (!res.ok) throw new Error('Failed to update plan');
  }

  static async triggerImages(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/generate-images`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger images');
  }

  static async triggerVideo(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/generate-video`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger video');
  }

  static async triggerPodcast(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/generate-podcast`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger podcast');
  }

  static async triggerSocial(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/generate-social`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger social');
  }

  static async triggerQA(id: string): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/api/jobs/${id}/run-qa`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to trigger QA');
  }

  static getFileUrl(jobId: string, filename: string): string {
    return `${API_BASE_URL}/api/files/${jobId}/${filename}`;
  }
}

export class WebSocketClient {
  private ws: WebSocket | null = null;

  connect(jobId: string, onMessage: (event: AgentEvent) => void, onDisconnect?: () => void) {
    if (this.ws) {
      this.ws.close();
    }

    this.ws = new WebSocket(`${WS_BASE_URL}/ws/${jobId}`);

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'ping') return; // Ignore keepalive pings
        onMessage(data as AgentEvent);
      } catch (err) {
        console.error('Failed to parse WebSocket message', err);
      }
    };

    this.ws.onerror = (err) => {
      console.error('WebSocket error:', err);
    };

    this.ws.onclose = () => {
      console.log(`WebSocket disconnected for job ${jobId}`);
      if (onDisconnect) onDisconnect();
    };
  }

  disconnect() {
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }
}
