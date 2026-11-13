import { Button, Progress } from 'antd';
import { Check, LoaderCircle, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { DocumentJob } from './document-types';

export const documentActive = (status: string) =>
	['uploading', 'queued', 'extracting', 'ai_queued', 'analysing'].includes(status);

export function DocumentProgress({ job, resume }: { job: DocumentJob; resume: () => void }) {
	const [now, setNow] = useState(Date.now());
	const active = documentActive(job.status);
	useEffect(() => {
		if (!active) return;
		const timer = window.setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(timer);
	}, [active]);
	const progress = job.payload.progress;
	const stage = progress?.stage;
	const page = progress?.page;
	const paused = ['needs_ocr', 'failed', 'needs_ai', 'needs_budget', 'text_ready'].includes(
		job.status,
	);
	const title =
		job.status === 'uploading'
			? 'Получаем файл'
			: job.status === 'queued'
				? job.processed
					? 'Продолжаем чтение'
					: 'Файл готов к обработке'
				: job.status === 'ai_queued'
					? 'Передаём страницы ИИ'
					: job.status === 'analysing'
						? `ИИ обрабатывает страницу ${page || '…'}`
						: job.status === 'extracting'
							? `${stage === 'rendering' ? 'Готовим' : stage === 'ocr' ? 'Распознаём' : stage === 'table_ocr' ? 'Читаем таблицы на' : 'Читаем'} страницу ${page || job.processed + 1}`
							: job.status === 'needs_ai'
								? 'Нужно подключить ИИ'
								: job.status === 'needs_budget'
									? 'Достигнут лимит обработки'
									: job.status === 'needs_ocr'
										? 'Нужно распознавание текста'
										: job.status === 'failed'
											? 'Обработка остановлена'
											: 'Страницы прочитаны';
	const seconds = Math.max(0, Math.floor((now - Date.parse(job.updated_at)) / 1000));
	const size = job.payload.file_bytes
		? `${(job.payload.file_bytes / 1048576).toLocaleString('ru', { maximumFractionDigits: 1 })} МБ`
		: '';
	const done = job.payload.analysis_done || 0;
	const total = job.payload.analysis_total || 0;
	const percent = Math.round((job.processed / Math.max(1, job.pages)) * 100);
	return (
		<section className="document-analysis document-live-progress" role="status" aria-live="polite">
			<div className="document-section-title">
				<h2>
					{active ? (
						<LoaderCircle size={17} className="spinning" />
					) : paused ? (
						<TriangleAlert size={17} />
					) : (
						<Check size={17} />
					)}
					{title}
				</h2>
			</div>
			<div className="document-progress-metadata">
				{job.pages ? `${job.pages} стр.` : 'Определяем число страниц'}
				{size && ` · ${size}`}
			</div>
			<div className="document-progress-counts">
				<span>Прочитано страниц</span>
				<strong>
					{job.processed} / {job.pages || '…'}
				</strong>
			</div>
			{job.pages > 0 && (
				<Progress
					size="small"
					percent={percent}
					showInfo={false}
					status={active && job.processed < job.pages ? 'active' : 'normal'}
				/>
			)}
			{(total > 0 || ['ai_queued', 'analysing'].includes(job.status)) && (
				<div className="document-progress-counts">
					<span>Проверено ИИ фрагментов</span>
					<strong>
						{done} / {total || '…'}
					</strong>
				</div>
			)}
			{job.payload.groups?.length ? (
				<div className="document-progress-counts">
					<span>Найдено позиций</span>
					<strong>{job.payload.groups.length}</strong>
				</div>
			) : null}
			{active && (
				<small className="document-progress-live">
					{seconds > 45
						? 'Обновление задерживается — проверяем обработку'
						: ['queued', 'ai_queued'].includes(job.status)
							? 'Запуск автоматический. Статус обновляется.'
							: 'Обрабатываем · обновление каждые 2 секунды'}
				</small>
			)}
			{paused && job.payload.notice && (
				<p className="document-progress-notice">{job.payload.notice}</p>
			)}
			{paused && (
				<Button onClick={resume}>
					{job.status === 'failed' ? 'Повторить обработку' : 'Продолжить обработку'}
				</Button>
			)}
		</section>
	);
}
