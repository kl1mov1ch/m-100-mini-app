import type {} from '../types';
export const previewUser = new URLSearchParams(location.search).get('as');
export function headers(project?: string) {
	return {
		'X-Telegram-Init-Data': window.Telegram?.WebApp?.initData || '',
		...(project ? { 'X-Project-Id': project } : {}),
		...(previewUser ? { 'X-Preview-User': previewUser } : {}),
	};
}
export async function request<T>(
	path: string,
	body?: unknown,
	project?: string,
	signal?: AbortSignal,
): Promise<T> {
	const form = body instanceof FormData;
	const r = await fetch('/api' + path, {
		method: body === undefined ? 'GET' : 'POST',
		headers: {
			...headers(project),
			...(!form ? { 'Content-Type': 'application/json' } : {}),
		},
		...(body !== undefined ? { body: form ? body : JSON.stringify(body) } : {}),
		signal,
	});
	if (!r.ok) {
		let d;
		try {
			d = await r.json();
		} catch {
			throw new Error('Нет соединения с сервером');
		}
		throw new Error(
			typeof d.detail === 'string' ? d.detail : d.detail?.message || 'Проверьте введённые данные',
		);
	}
	return r.json();
}
