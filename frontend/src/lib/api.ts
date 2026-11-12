import type {} from '../types';
export const previewUser = new URLSearchParams(location.search).get('as');
export class RequestError extends Error {
	constructor(
		message: string,
		readonly code?: string,
	) {
		super(message);
	}
}
export function headers(project?: string) {
	return {
		'X-Telegram-Init-Data': window.Telegram?.WebApp?.initData || '',
		'X-View-Mode': localStorage.getItem('view-mode') || 'admin',
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
		const detail = typeof d.detail === 'string' ? d.detail : d.detail?.message;
		throw new RequestError(
			detail === 'Not Found'
				? 'Этот раздел недоступен. Обновите приложение.'
				: detail || 'Проверьте введённые данные',
			typeof d.detail?.code === 'string' ? d.detail.code : undefined,
		);
	}
	return r.json();
}
