import { App, Button, Input, Select } from 'antd';
import { Building2, CheckCircle2, CloudUpload, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { request } from '../lib/api';
import type { DiskWebhook } from '../types';
import type { DocumentJob } from './document-types';

export function DocumentPublishPanel({
	job,
	refresh,
	openObject,
}: {
	job: DocumentJob;
	refresh: (job: DocumentJob) => void;
	openObject?: (id: string) => void;
}) {
	const { message } = App.useApp();
	const [hooks, setHooks] = useState<DiskWebhook[]>([]),
		[url, setUrl] = useState(job.payload.publication?.public_url || ''),
		[hook, setHook] = useState<string | undefined>(job.payload.publication?.webhook_id),
		[name, setName] = useState(
			job.payload.publication?.object_name ||
				job.name
					.replace(/\.pdf$/i, '')
					.replace(/_/g, ' ')
					.slice(0, 100),
		),
		[busy, setBusy] = useState(false),
		[hooksLoaded, setHooksLoaded] = useState(false),
		[error, setError] = useState('');
	const target = job.payload.publication;
	const ready = job.status === 'ready';
	const retrying = ['publish_retry', 'publishing'].includes(job.status);
	const direct = target?.mode === 'disk';
	useEffect(() => {
		if (!ready) return;
		const controller = new AbortController();
		void request<DiskWebhook[]>('/documents/webhooks', undefined, undefined, controller.signal)
			.then((items) => {
				setHooks(items);
				setHooksLoaded(true);
				setHook((current) =>
					items.some((item) => item.id === current)
						? current
						: items.length === 1
							? items[0].id
							: undefined,
				);
			})
			.catch((error) => {
				if (!controller.signal.aborted) setError(error.message);
			});
		return () => controller.abort();
	}, [ready]);
	const previewed =
		ready &&
		target?.phase === 'preview' &&
		target.public_url === url.trim() &&
		target.webhook_id === hook &&
		target.object_name === name.trim();
	const act = async (action: 'upload' | 'connect' | 'preview' | 'publish' | 'reset') => {
		setBusy(true);
		setError('');
		try {
			const next = await request<DocumentJob>(
				`/documents/${job.id}/bitrix/${action}`,
				action === 'preview' || action === 'upload'
					? {
							version: job.updated_at,
							...(action === 'preview' && { public_url: url.trim() }),
							webhook_id: hook,
							object_name: name.trim(),
						}
					: action === 'reset'
						? {}
						: { version: job.updated_at, token: target?.token },
			);
			refresh(next);
			if (next.status === 'published') message.success('Объект создан');
		} catch (failure) {
			setError((failure as Error).message);
			try {
				refresh(await request<DocumentJob>(`/documents/${job.id}`));
			} catch {
				setError((current) => current || 'Не удалось обновить документ');
			}
		} finally {
			setBusy(false);
		}
	};
	const saved = job.status === 'uploaded' || job.status === 'published';
	const tableUrl = target?.detail_url || target?.public_url;
	if (saved && target)
		return (
			<section className="document-publish-panel">
				<div className="document-section-title">
					<h2>
						<CheckCircle2 size={18} />{' '}
						{job.status === 'uploaded' ? 'Смета на Диске Битрикс24' : 'Объект создан'}
					</h2>
				</div>
				<strong>{target.object_name}</strong>
				{job.status === 'uploaded' && (
					<small>Добавьте объект, чтобы вести по этой таблице отчёты.</small>
				)}
				<div className="document-publish-actions">
					{job.status === 'uploaded' ? (
						<Button
							type="primary"
							icon={<Building2 size={16} />}
							loading={busy}
							onClick={() => void act('connect')}
						>
							Добавить в объекты
						</Button>
					) : (
						openObject && (
							<Button
								type="primary"
								icon={<Building2 size={16} />}
								onClick={() => openObject(target.project_id)}
							>
								Открыть объект
							</Button>
						)
					)}
					{tableUrl && (
						<a href={tableUrl} target="_blank" rel="noreferrer">
							<ExternalLink size={15} /> Открыть таблицу
						</a>
					)}
				</div>
				{error && (
					<p className="document-question" role="alert">
						{error}
					</p>
				)}
			</section>
		);
	if (!ready && !retrying) return null;
	const missing = !hooks.some((item) => item.id === hook) || !name.trim();
	return (
		<section className="document-publish-panel">
			<div className="document-section-title">
				<h2>{ready ? 'Утверждённая смета' : 'Загрузка в Битрикс24'}</h2>
			</div>
			{ready ? (
				<>
					<small>Загрузите Excel на Диск Битрикс24, затем добавьте таблицу в объекты.</small>
					<label>
						Название объекта
						<Input
							value={name}
							maxLength={100}
							disabled={busy}
							onChange={(event) => setName(event.target.value)}
						/>
					</label>
					{hooks.length > 0 && (
						<label>
							Подключение Диска
							<Select
								value={hook}
								disabled={busy}
								placeholder="Выберите подключение"
								onChange={setHook}
								options={hooks.map((item) => ({ value: item.id, label: item.name }))}
							/>
						</label>
					)}
					{hooksLoaded && !hooks.length && (
						<small>Добавьте подключение Диска Битрикс24 в настройках профиля.</small>
					)}
					<Button
						type="primary"
						icon={<CloudUpload size={16} />}
						loading={busy}
						disabled={missing}
						onClick={() => void act('upload')}
					>
						Загрузить в Битрикс24
					</Button>
					<details
						className="document-details document-publish-existing"
						open={previewed || undefined}
					>
						<summary>Уже есть пустой XLSX на Диске</summary>
						<label>
							Публичная ссылка на пустой XLSX
							<Input
								type="url"
								inputMode="url"
								value={url}
								disabled={busy}
								placeholder="https://bitrix24public.com/…"
								onChange={(event) => setUrl(event.target.value)}
							/>
						</label>
						<Button
							disabled={missing || !url.trim() || busy}
							onClick={() => void act(previewed ? 'publish' : 'preview')}
						>
							{previewed ? 'Записать в файл и создать объект' : 'Проверить пустой файл'}
						</Button>
					</details>
				</>
			) : (
				<>
					<small>
						{direct
							? job.status === 'publishing'
								? 'Проверяем загрузку файла на Диск.'
								: 'Загрузка не подтверждена. При повторе проверим, сохранился ли файл на Диске.'
							: job.payload.notice || 'Проверяем запись таблицы.'}
					</small>
					<Button
						type="primary"
						loading={busy}
						onClick={() => void act(direct ? 'upload' : 'publish')}
					>
						{direct ? 'Проверить загрузку' : 'Проверить запись'}
					</Button>
					{!direct && job.status === 'publish_retry' && (
						<Button type="text" disabled={busy} onClick={() => void act('reset')}>
							Выбрать другой файл
						</Button>
					)}
				</>
			)}
			{error && (
				<p className="document-question" role="alert">
					{error}
				</p>
			)}
		</section>
	);
}
