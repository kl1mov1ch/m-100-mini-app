import { useCallback, useEffect, useRef, useState } from 'react';

export function useTelegramNotifications(userId?: string) {
	const app = window.Telegram?.WebApp;
	const supported = Boolean(app?.initData && app.requestWriteAccess && app.isVersionAtLeast('6.9'));
	const alreadyAllowed = app?.initDataUnsafe?.user?.allows_write_to_pm === true;
	const key = userId ? `telegram-notifications:${userId}` : '';
	const attempted = useRef(new Set<string>());
	const [result, setResult] = useState<{ key: string; granted: boolean }>();
	const [requesting, setRequesting] = useState(false);

	const requestPermission = useCallback(() => {
		if (!supported || !key || alreadyAllowed || attempted.current.has(key + ':pending')) return;
		attempted.current.add(key);
		attempted.current.add(key + ':pending');
		setRequesting(true);
		try {
			app!.requestWriteAccess!((granted) => {
				attempted.current.delete(key + ':pending');
				setResult({ key, granted });
				setRequesting(false);
				try {
					localStorage.setItem(key, granted ? 'granted' : 'declined');
				} catch {
					// This session still remembers the response when storage is unavailable.
				}
			});
		} catch {
			attempted.current.delete(key + ':pending');
			setRequesting(false);
		}
	}, [alreadyAllowed, app, key, supported]);

	useEffect(() => {
		if (!supported || !key || alreadyAllowed || attempted.current.has(key)) return;
		try {
			const previous = localStorage.getItem(key);
			if (previous === 'declined' || previous === 'granted') return;
		} catch {
			// Telegram will still show its native dialog.
		}
		requestPermission();
	}, [alreadyAllowed, key, requestPermission, supported]);

	return {
		supported,
		granted: alreadyAllowed || (result?.key === key && result.granted),
		requesting,
		requestPermission,
	};
}
