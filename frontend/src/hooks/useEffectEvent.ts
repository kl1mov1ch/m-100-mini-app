import { useCallback, useLayoutEffect, useRef } from 'react';

export function useEffectEvent<Args extends unknown[], Result>(
	callback: (...args: Args) => Result,
) {
	const latest = useRef(callback);
	useLayoutEffect(() => {
		latest.current = callback;
	}, [callback]);
	return useCallback((...args: Args) => latest.current(...args), []);
}
