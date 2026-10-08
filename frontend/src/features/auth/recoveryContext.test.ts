import { beforeEach, describe, expect, it } from 'vitest';
import {
  forgetRecoveryAccount,
  recoveryAccount,
  rememberRecoveryAccount,
} from './recoveryContext';

beforeEach(() => {
  sessionStorage.clear();
  localStorage.clear();
});

describe('offline recovery account context', () => {
  it('requires a previously confirmed account in both the document and device hints', () => {
    expect(recoveryAccount()).toBeNull();
    rememberRecoveryAccount('a');
    expect(recoveryAccount()).toBe('a');
    sessionStorage.setItem('basefit.recovery-account', 'unknown');
    expect(recoveryAccount()).toBeNull();
  });

  it('blocks an older tab after a different account is confirmed, and after a 401', () => {
    rememberRecoveryAccount('a');
    localStorage.setItem('basefit.recovery-account', 'b');
    expect(recoveryAccount()).toBeNull();
    rememberRecoveryAccount('b');
    forgetRecoveryAccount();
    expect(recoveryAccount()).toBeNull();
  });
});
