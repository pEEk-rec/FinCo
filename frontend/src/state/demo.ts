import { useEffect } from 'react';
import { useSearchParams } from 'react-router';

/**
 * Demo mode shows the tools that exist only to demonstrate FinCo: the payment simulator and the
 * design-system page. Turn it on with `?demo=1` (remembered on this device), off with `?demo=0`.
 */

const KEY = 'finco.demo';

function stored(): boolean {
  try {
    return localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export function useDemoMode(): boolean {
  const [params] = useSearchParams();
  const flag = params.get('demo');
  useEffect(() => {
    try {
      if (flag === '1') localStorage.setItem(KEY, '1');
      if (flag === '0') localStorage.removeItem(KEY);
    } catch {
      /* storage blocked: the flag still works for this page */
    }
  }, [flag]);
  return flag === '1' || (flag !== '0' && stored());
}
