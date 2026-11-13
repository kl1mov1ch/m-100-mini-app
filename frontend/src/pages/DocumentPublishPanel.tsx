import { App, Button, Input, Select } from 'antd';
import { Building2, CheckCircle2, ExternalLink } from 'lucide-react';
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
		[error, setError] = useState('');
	useEffect(() => {
		const controller = new AbortController();
		void request<DiskWebhook[]>('/documents/webhooks', undefined, undefined, controller.signal)
			.then((items) => {
				setHooks(items);
				if (items.length === 1) setHook((current) => current || items[0].id);
			})
			.catch((error) => {
				if (!controller.signal.aborted) setError(error.message);
			});
		return () => controller.abort();
	}, []);
	const target = job.payload.publication;
	const ready = job.status === 'ready';
	const previewed =
		ready &&
		target?.phase === 'preview' &&
		target.public_url === url.trim() &&
		target.webhook_id === hook &&
		target.object_name === name.trim();
	const retrying = ['publish_retry', 'publishing'].includes(job.status);
	const act = async (action: string) => {
		setBusy(true);
		setError('');
		try {
			const next = await request<DocumentJob>(
				`/documents/${job.id}/bitrix/${action}`,
				action === 'preview'
					? {
							version: job.updated_at,
							public_url: url.trim(),
							webhook_id: hook,
							object_name: name.trim(),
						}
					: action === 'reset'
						? {}
						: { version: job.updated_at, token: target?.token },
			);
			refresh(next);
			if (next.status === 'published') message.success('Таблица записана, объект создан');
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
	if (job.status === 'published' && target)
		return (
			<section className="document-publish-panel">
				<div className="document-section-title">
					<h2>
						<CheckCircle2 size={18} /> Объект создан
					</h2>
				</div>
				<strong>{target.object_name}</strong>
				<div className="document-publish-actions">
					{openObject && (
						<Button
							type="primary"
							icon={<Building2 size={16} />}
							onClick={() => openObject(target.project_id)}
						>
							Открыть объект
						</Button>
					)}
					<a href={target.public_url} target="_blank" rel="noreferrer">
						<ExternalLink size={15} /> Таблица
					</a>
				</div>
			</section>
		);
	return (
		<section className="document-publish-panel">
			<div className="document-section-title">
				<h2>Таблица для объекта</h2>
			</div>
			{!ready && !retrying ? (
				<small>
					Сначала проверьте строки и укажите расценки. Затем вставьте ссылку на пустой файл
					Битрикс24.
				</small>
			) : (
				<>
					<label>
						Публичная ссылка на пустой XLSX
						<Input
							type="url"
							inputMode="url"
							value={url}
							disabled={busy || retrying}
							placeholder="https://bitrix24public.com/…"
							onChange={(event) => setUrl(event.target.value)}
						/>
					</label>
					<label>
						Подключение Диска
						<Select
							value={hook}
							disabled={busy || retrying}
							placeholder="Выберите сохранённый вебхук"
							onChange={setHook}
							options={hooks.map((item) => ({ value: item.id, label: item.name }))}
						/>
					</label>
					{!hooks.length && <small>Добавьте вебхук Диска в настройках профиля.</small>}
					<details className="document-details">
						<summary>Название объекта</summary>
						<Input
							value={name}
							maxLength={100}
							disabled={busy || retrying}
							onChange={(event) => setName(event.target.value)}
						/>
					</details>
					{previewed && (
						<div className="document-target-preview">
							<CheckCircle2 size={16} />
							<span>
								{target.name}
								<small>Пустой файл проверен · {job.payload.groups?.length} работ</small>
							</span>
						</div>
					)}
					{retrying && (
						<small>
							{job.payload.notice ||
								'Проверяем запись таблицы. Повторная проверка не дублирует объект.'}
						</small>
					)}
					<Button
						type="primary"
						loading={busy}
						disabled={!retrying && (!url.trim() || !hook || !name.trim())}
						onClick={() => void act(retrying || previewed ? 'publish' : 'preview')}
					>
						{retrying
							? 'Проверить запись'
							: previewed
								? 'Создать таблицу и объект'
								: 'Проверить пустой файл'}
					</Button>
					{job.status === 'publish_retry' && (
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
