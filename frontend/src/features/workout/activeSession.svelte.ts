import { listWorkouts } from '../../api';

class ActiveSessionState {
  workoutId = $state<string | null>(null);
  status = $state<'idle' | 'loading' | 'ready' | 'error'>('idle');
  private accountId: string | null = null;

  async refresh(accountId: string): Promise<void> {
    this.accountId = accountId;
    this.status = 'loading';
    try {
      const page = await listWorkouts({
        status: 'active',
        page: 1,
        pageSize: 2,
      });
      if (this.accountId !== accountId) return;
      this.workoutId = page.items[0]?.id ?? null;
      this.status = 'ready';
    } catch {
      if (this.accountId === accountId) this.status = 'error';
    }
  }

  setActive(workoutId: string): void {
    this.workoutId = workoutId;
    this.status = 'ready';
  }

  clear(workoutId?: string): void {
    if (workoutId === undefined || this.workoutId === workoutId) {
      this.workoutId = null;
      this.status = 'ready';
    }
  }

  reset(): void {
    this.accountId = null;
    this.workoutId = null;
    this.status = 'idle';
  }
}

export const activeSession = new ActiveSessionState();
