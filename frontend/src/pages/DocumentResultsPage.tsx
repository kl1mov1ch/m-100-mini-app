import { App, Button, Checkbox, Input, InputNumber, Modal, Segmented, Select } from 'antd';
import {
	ArrowLeft,
	ChevronLeft,
	ChevronRight,
	Download,
	FileSearch,
	Images,
	ZoomIn,
	ZoomOut,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Money, nf } from '../lib/format';
import { headers, request } from '../lib/api';
import { downloadReport } from '../lib/report-download';
import type { DocumentJob, DocumentGroup, DocumentSource } from './document-types';
import { DocumentPublishPanel } from './DocumentPublishPanel';
import { CompactRow } from '../components/CompactRow';

function pageMentions(row: DocumentGroup) {
	const pages = new Map<number, number>();
	row.sources.forEach((source) => pages.set(source.page, (pages.get(source.page) || 0) + 1));
	return [...pages]
		.sort(([a], [b]) => a - b)
		.map(([page, count]) => `стр. ${page} — ${count} упомин.`)
		.join('; ');
}

function SourcePreview({
	jobId,
	page,
	highlights,
	turn,
}: {
	jobId: string;
	page: number;
	highlights?: DocumentSource['highlights'];
	turn: (direction: number) => void;
}) {
	const [url, setUrl] = useState(''),
		[error, setError] = useState('');
	const [zoom, setZoom] = useState(false);
	const swipe = useRef<{ x: number; y: number } | null>(null);
	useEffect(() => {
		const controller = new AbortController();
		let objectUrl = '';
		setError('');
		void fetch(`/api/documents/${jobId}/pages/${page}/preview`, {
			headers: headers(),
			signal: controller.signal,
		})
			.then(async (response) => {
				if (!response.ok) throw new Error('Для этой страницы доступна текстовая цитата.');
				objectUrl = URL.createObjectURL(await response.blob());
				if (controller.signal.aborted) URL.revokeObjectURL(objectUrl);
				else setUrl(objectUrl);
			})
			.catch((error) => {
				if (!controller.signal.aborted) setError((error as Error).message);
			});
		return () => {
			controller.abort();
			URL.revokeObjectURL(objectUrl);
			setUrl('');
		};
	}, [jobId, page]);
	return (
		<div className="document-page-preview">
			{error ? (
				<p>{error}</p>
			) : url ? (
				<>
					<div
						className="document-gallery-canvas"
						onTouchStart={(event) => {
							const touch = event.touches[0];
							swipe.current = !zoom && touch ? { x: touch.clientX, y: touch.clientY } : null;
						}}
						onTouchEnd={(event) => {
							const start = swipe.current;
							swipe.current = null;
							const touch = event.changedTouches[0];
							if (!start || !touch) return;
							const x = touch.clientX - start.x;
							if (Math.abs(x) > 45 && Math.abs(x) > 2 * Math.abs(touch.clientY - start.y))
								turn(x < 0 ? 1 : -1);
						}}
					>
						<div className={`document-highlight-page${zoom ? ' is-zoomed' : ''}`}>
							<img src={url} alt={`Страница ${page} с выделениями выбранной работы`} />
							{highlights?.map((box, index) => (
								<span
									key={index}
									style={{
										left: `${box.left}%`,
										top: `${box.top}%`,
										width: `${box.width}%`,
										height: `${box.height}%`,
									}}
								/>
							))}
						</div>
					</div>
					<Button
						type="text"
						icon={zoom ? <ZoomOut size={16} /> : <ZoomIn size={16} />}
						onClick={() => setZoom(!zoom)}
					>
						{zoom ? 'Уменьшить' : 'Увеличить'}
					</Button>
				</>
			) : (
				<p role="status">Загружаем страницу…</p>
			)}
		</div>
	);
}

function SourceGallery({ jobId, group }: { jobId: string; group: DocumentGroup }) {
	const [selected, setSelected] = useState<number>();
	const pages = new Map<number, NonNullable<DocumentSource['highlights']>>();
	for (const source of group.sources) {
		for (const evidence of [source, ...(source.highlight_pages || [])]) {
			pages.set(evidence.page, [
				...(pages.get(evidence.page) || []),
				...(evidence.highlights || []),
			]);
		}
	}
	const numbers = [...pages.keys()].sort((a, b) => a - b);
	const page = selected ?? numbers[0];
	const index = numbers.indexOf(page);
	const mentions = group.sources.filter((source) => source.page === page);
	const highlights = [
		...new Map((pages.get(page) || []).map((box) => [JSON.stringify(box), box])).values(),
	];
	if (!numbers.length) return <p>Источники для этой позиции не сохранены.</p>;
	return (
		<div className="document-source document-source-gallery">
			<div className="document-gallery-nav">
				<Button
					type="text"
					aria-label="Предыдущая страница"
					icon={<ChevronLeft size={18} />}
					disabled={index === 0}
					onClick={() => setSelected(numbers[index - 1])}
				/>
				<Select
					aria-label="Страница источника"
					value={page}
					onChange={setSelected}
					options={numbers.map((number) => ({ value: number, label: `Страница ${number}` }))}
				/>
				<span aria-live="polite">
					{index + 1} / {numbers.length}
				</span>
				<Button
					type="text"
					aria-label="Следующая страница"
					icon={<ChevronRight size={18} />}
					disabled={index === numbers.length - 1}
					onClick={() => setSelected(numbers[index + 1])}
				/>
			</div>
			<SourcePreview
				key={page}
				jobId={jobId}
				page={page}
				highlights={highlights}
				turn={(direction) => setSelected(numbers[index + direction] ?? page)}
			/>
			{!mentions.length && (
				<small className="page-context">На этой странице продолжается наименование работы.</small>
			)}
			{mentions.map((source, index) => (
				<details key={index}>
					<summary>
						{source.source_row != null && `Строка ${source.source_row} · `}
						{source.original_quantity ?? 'Объём не определён'} {source.original_unit}
					</summary>
					<blockquote>{source.quote}</blockquote>
					{source.evidence_warning ? (
						<p className="document-question">{source.evidence_warning}</p>
					) : source.visual_verified || source.local_verified ? (
						<small className="page-context">Количество сверено по ячейке PDF</small>
					) : null}
					{source.question && <p className="document-question">{source.question}</p>}
					{source.geometry_factor && <p>Площадь поверхности: {source.quantity} м²</p>}
				</details>
			))}
		</div>
	);
}

export function DocumentResultsPage({
	job,
	back,
	refresh,
	recheck,
	embedded = false,
	openObject,
}: {
	job: DocumentJob;
	back: () => void;
	refresh: (job: DocumentJob) => void;
	recheck?: () => Promise<void>;
	embedded?: boolean;
	openObject?: (id: string) => void;
}) {
	const [category, setCategory] = useState('Все'),
		[status, setStatus] = useState('all'),
		[query, setQuery] = useState(''),
		[editing, setEditing] = useState<DocumentGroup | null>(null),
		[sources, setSources] = useState<DocumentGroup | null>(null),
		[quantity, setQuantity] = useState<string | null>(null),
		[rate, setRate] = useState<string | null>(null),
		[unit, setUnit] = useState('м'),
		[name, setName] = useState(''),
		[editCategory, setEditCategory] = useState(''),
		[section, setSection] = useState(''),
		[subsection, setSubsection] = useState(''),
		[notes, setNotes] = useState(''),
		[resolution, setResolution] = useState<string>(),
		[acknowledge, setAcknowledge] = useState(false),
		[saving, setSaving] = useState(false),
		[checking, setChecking] = useState(false),
		[download, setDownload] = useState<'excel' | 'pdf' | null>(null);
	const { message } = App.useApp();
	const groups = job.payload.groups || [];
	const disciplines = [...new Set(groups.map((row) => row.category))].sort((left, right) => {
		if (left === 'Отопление') return -1;
		if (right === 'Отопление') return 1;
		return left.localeCompare(right, 'ru');
	});
	const categories = ['Все', ...disciplines];
	const currentCategory = categories.includes(category) ? category : 'Все';
	const rows = groups.filter(
		(row) =>
			(currentCategory === 'Все' || row.category === currentCategory) &&
			(status === 'all' || (status === 'pending' ? !row.confirmed : row.confirmed)) &&
			row.name.toLowerCase().includes(query.toLowerCase()),
	);
	const summary = job.payload.summary;
	const readOnly = !['ready', 'needs_review', 'draft'].includes(job.status);
	useEffect(() => {
		setEditing(null);
	}, [readOnly]);
	const needsScope = !!(
		job.payload.coverage?.drawings?.length ||
		job.payload.coverage?.low_ocr?.length ||
		job.payload.coverage?.questions
	);
	const suggestedRate = editing?.rate_suggestion;
	const usingSuggestion = suggestedRate && rate !== null && Number(rate) === Number(editing?.rate);
	const clearSuggestedRate = () => {
		if (usingSuggestion) setRate(null);
	};
	const eligible = rows
		.filter(
			(row) =>
				!readOnly &&
				!row.confirmed &&
				!row.issues.length &&
				row.quantity !== null &&
				row.rate != null,
		)
		.slice(0, 100);
	const confirmBatch = async () => {
		setSaving(true);
		try {
			const next = await request<DocumentJob>(`/documents/${job.id}/review`, {
				version: job.updated_at,
				acknowledge_scope: acknowledge,
				items: eligible.map((row) => ({
					group_id: row.id,
					quantity: String(row.quantity),
					rate: row.rate,
					unit: row.unit,
					notes: row.notes,
					resolution: row.quantity_mode,
				})),
			});
			refresh(next);
			message.success(`Подтверждено строк: ${eligible.length}`);
		} catch (error) {
			message.error((error as Error).message);
			refresh(await request<DocumentJob>(`/documents/${job.id}`));
		} finally {
			setSaving(false);
		}
	};
	const choose = (row: DocumentGroup) => {
		setEditing(row);
		setSources(null);
		setQuantity(row.quantity === null ? null : String(row.quantity));
		setRate(row.rate === null ? null : String(row.rate));
		setUnit(row.unit || 'м');
		setName(row.name);
		setEditCategory(row.category);
		setSection(row.section || '');
		setSubsection(row.subsection || '');
		setNotes(pageMentions(row));
		setResolution(row.quantity === null ? undefined : row.quantity_mode || 'manual');
		setAcknowledge(false);
	};
	const confirm = async () => {
		if (readOnly || !editing || quantity === null || rate === null) return;
		setSaving(true);
		try {
			const next = await request<DocumentJob>('/documents/' + job.id + '/groups/' + editing.id, {
				version: job.updated_at,
				quantity,
				rate,
				unit,
				name,
				category: editCategory,
				section,
				subsection,
				notes,
				resolution,
				acknowledge_scope: acknowledge,
			});
			refresh(next);
			setEditing(null);
			message.success('Позиция подтверждена');
		} catch (error) {
			message.error((error as Error).message);
			const fresh = await request<DocumentJob>('/documents/' + job.id);
			refresh(fresh);
		} finally {
			setSaving(false);
		}
	};
	const exportFile = async (kind: 'excel' | 'pdf') => {
		setDownload(kind);
		try {
			const final = ['ready', 'uploaded', 'published'].includes(job.status);
			const file = kind === 'pdf' ? 'marked.pdf' : 'export.xlsx' + (final ? '?final=true' : '');
			await downloadReport('/documents/' + job.id + '/' + file);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setDownload(null);
		}
	};

	return (
		<div className="document-page document-results-page">
			{!embedded && (
				<button className="back-link" onClick={back}>
					<ArrowLeft size={16} />
					Документы
				</button>
			)}
			<div className="page-title document-results-title">
				<div>
					{embedded ? <h2>Сводная смета</h2> : <h1>Сводная смета</h1>}
					{['queued', 'ai_queued', 'extracting', 'analysing'].includes(job.status) && (
						<small className="page-context">Предварительные данные · обработка продолжается</small>
					)}
					{!embedded && <small className="page-context document-filename">{job.name}</small>}
				</div>
			</div>
			<div className="document-export-actions" aria-label="Скачать результаты">
				<Button
					icon={<Download size={16} />}
					loading={download === 'excel'}
					disabled={download === 'pdf'}
					onClick={() => void exportFile('excel')}
				>
					Скачать Excel
				</Button>
				<Button
					icon={<FileSearch size={16} />}
					loading={download === 'pdf'}
					disabled={download === 'excel'}
					onClick={() => void exportFile('pdf')}
				>
					PDF с выделением
				</Button>
			</div>
			<section className="document-result-summary">
				<div>
					<span>
						<small>Подтверждено</small>
						<strong>
							{summary?.confirmed || 0} / {groups.length}
						</strong>
					</span>
					<span>
						<small>Проверенная сумма</small>
						<strong>
							<Money value={summary?.amount || 0} />
						</strong>
					</span>
				</div>
			</section>
			<DocumentPublishPanel job={job} refresh={refresh} openObject={openObject} />
			<details className="document-checks">
				<summary>
					Проверка источников{' '}
					<span>
						· {job.processed}/{job.pages} стр.
						{summary?.unresolved ? ` · ${summary.unresolved} к сверке` : ''}
						{job.payload.questions?.length ? ` · ${job.payload.questions.length} вопросов` : ''}
					</span>
				</summary>
				<p>{job.payload.query}</p>
				<p>В сумме — только проверенные строки с расценками.</p>
				{job.payload.selection_complete && (
					<p>
						{job.payload.scope_categories?.length
							? `${job.payload.scope_categories.join(' · ')}. Листы с нужными строками: ${job.payload.scope_pages?.join(', ') || 'не найдены'}.`
							: `Листы с таблицами: ${job.payload.selected_specifications?.join(', ') || 'не найдены'}.`}
					</p>
				)}
				{!job.payload.coverage?.complete && (
					<p>Обработка неполная — итоговый отчёт пока недоступен.</p>
				)}
				{needsScope && (
					<p>
						Есть вопросы к полноте или качеству распознавания. Геометрические длины и площади по
						изображениям не измерялись. Проверьте источники отмеченных строк.
					</p>
				)}
				{!!job.payload.questions?.length && (
					<ul>
						{job.payload.questions.map((question, index) => (
							<li key={index}>{question}</li>
						))}
					</ul>
				)}
				{recheck && (
					<Button
						type="link"
						loading={checking}
						onClick={async () => {
							setChecking(true);
							try {
								await recheck();
							} finally {
								setChecking(false);
							}
						}}
					>
						Перепроверить PDF
					</Button>
				)}
			</details>
			{disciplines.length > 1 && (
				<div className="document-category-switch">
					<Segmented<string>
						aria-label="Категория выборки"
						value={currentCategory}
						onChange={setCategory}
						options={categories}
					/>
				</div>
			)}
			<div className="document-results-filters">
				<Input.Search
					placeholder="Найти работу"
					value={query}
					onChange={(event) => {
						setQuery(event.target.value);
					}}
				/>
				<Select
					aria-label="Проверка строк"
					value={status}
					onChange={(value) => {
						setStatus(value);
					}}
					options={[
						{ value: 'all', label: 'Все строки' },
						{ value: 'pending', label: 'Требуют проверки' },
						{ value: 'confirmed', label: 'Подтверждены' },
					]}
				/>
			</div>
			{disciplines.map((discipline) => {
				const positions = rows.filter((row) => row.category === discipline);
				if (!positions.length) return null;
				return (
					<section className="document-work-category" aria-label={discipline} key={discipline}>
						{currentCategory === 'Все' && disciplines.length > 1 && <h3>{discipline}</h3>}
						<div className="document-works compact-list">
							{positions.map((row) => (
								<CompactRow
									key={row.id}
									className="document-review-row"
									title={row.name}
									description={
										row.quantity === null
											? 'Уточните объём'
											: nf.format(Number(row.quantity)) + ' ' + row.unit
									}
									value={
										row.rate !== null ? (
											<>
												<Money value={Number(row.rate)} /> / {row.unit}
											</>
										) : (
											'Нет расценки'
										)
									}
									meta={
										row.confirmed
											? 'Проверено'
											: row.issues.length
												? 'Нужна проверка'
												: row.rate_suggestion
													? 'Из справочника'
													: 'Черновик'
									}
									attention={!row.confirmed && !!row.issues.length}
									onClick={() => choose(row)}
								/>
							))}
						</div>
					</section>
				);
			})}
			{!rows.length && <p className="compact-empty">Работ по этим фильтрам нет</p>}
			{eligible.length > 0 && (
				<section className="document-batch-review">
					<small>Перед подтверждением проверьте объёмы и предложенные расценки.</small>
					{needsScope && !job.payload.acknowledge_scope && (
						<Checkbox
							checked={acknowledge}
							onChange={(event) => setAcknowledge(event.target.checked)}
						>
							Полнота выборки и вопросы проверены
						</Checkbox>
					)}
					<Button type="primary" loading={saving} onClick={() => void confirmBatch()}>
						Подтвердить строки · {eligible.length}
					</Button>
				</section>
			)}
			<Modal
				className="document-work-sheet"
				title={
					sources
						? sources.name
						: editing && (
								<div className="document-gallery-title">
									<span>{editing.name}</span>
									{!!editing.sources.length && (
										<Button
											type="text"
											aria-label="Галерея источников PDF"
											title="Галерея источников PDF"
											icon={<Images size={19} />}
											onClick={() => setSources(editing)}
										/>
									)}
								</div>
							)
				}
				width={sources ? 820 : undefined}
				open={!!editing}
				onCancel={() => (sources ? setSources(null) : !saving && setEditing(null))}
				confirmLoading={saving}
				destroyOnHidden
				{...(sources
					? { footer: <Button onClick={() => setSources(null)}>К позиции</Button> }
					: readOnly
						? { footer: <Button onClick={() => setEditing(null)}>Готово</Button> }
						: {})}
				okText="Подтвердить"
				cancelText="Отмена"
				onOk={() => !sources && void confirm()}
				okButtonProps={{
					disabled:
						quantity === null ||
						rate === null ||
						((editing?.issues.length || 0) > 0 && !resolution),
				}}
			>
				{sources ? (
					<SourceGallery jobId={job.id} group={sources} />
				) : readOnly ? (
					<div className="document-review-form">
						<dl className="position-totals">
							<div>
								<dt>По смете</dt>
								<dd>
									{editing?.quantity ?? 'Не определено'} {editing?.unit}
								</dd>
							</div>
							<div>
								<dt>За единицу</dt>
								<dd>
									{editing?.rate != null ? <Money value={Number(editing.rate)} /> : 'Не указано'}
								</dd>
							</div>
						</dl>
						<p>
							{[editing?.category, editing?.section, editing?.subsection]
								.filter(Boolean)
								.join(' · ')}
						</p>
						{editing && pageMentions(editing) && <p>{pageMentions(editing)}</p>}
					</div>
				) : (
					<div className="document-review-form">
						<div className="document-work-total">
							<span>Сумма по позиции</span>
							<strong>
								{quantity !== null && rate !== null ? (
									<Money value={Number(quantity) * Number(rate)} />
								) : (
									'Укажите объём и расценку'
								)}
							</strong>
						</div>
						<details className="document-details document-edit-details">
							<summary>Название и раздел</summary>
							<label>
								Название работы
								<Input
									value={name}
									maxLength={300}
									onChange={(event) => {
										clearSuggestedRate();
										setName(event.target.value);
									}}
								/>
							</label>
							<label>
								Категория
								<Select
									value={editCategory}
									onChange={(value) => {
										clearSuggestedRate();
										setEditCategory(value);
									}}
									options={[
										'Вентиляция',
										'Отопление',
										'Водоснабжение',
										'Канализация',
										'Кондиционирование',
										'Электроснабжение',
										'Автоматика',
										'Прочее',
									].map((value) => ({ value, label: value }))}
								/>
							</label>
							<label>
								Раздел в этом файле
								<Input
									value={section}
									onChange={(e) => setSection(e.target.value)}
									maxLength={160}
									placeholder="Дословный заголовок из файла"
								/>
							</label>
							<label>
								Подраздел
								<Input
									value={subsection}
									onChange={(e) => {
										clearSuggestedRate();
										setSubsection(e.target.value);
									}}
									maxLength={160}
								/>
							</label>
						</details>
						{editing?.issues.map((issue) => (
							<p className="document-question" key={issue}>
								{issue}
							</p>
						))}
						{!!editing?.sources.length && (
							<small className="page-context">
								Упоминаний: {editing.mention_count ?? editing.sources.length}
							</small>
						)}
						<div className="document-input-pair">
							<label>
								Единица измерения
								<Select
									value={unit}
									onChange={(value) => {
										clearSuggestedRate();
										setUnit(value);
										setResolution('manual');
									}}
									options={[
										'м',
										'м²',
										'м³',
										'шт.',
										'кг',
										'кВт',
										'компл.',
										'систем',
										'чел·ч',
										'чел·дн',
									].map((value) => ({
										value,
										label: value,
									}))}
								/>
							</label>
							<label>
								Объём
								<InputNumber
									stringMode
									min="0"
									max="1000000000"
									value={quantity}
									onChange={(value) => {
										setQuantity(value);
										setResolution('manual');
									}}
									controls={false}
								/>
							</label>
						</div>
						<label>
							Расценка за {unit}, BYN
							<InputNumber
								stringMode
								min="0"
								max="1000000000"
								value={rate}
								onChange={setRate}
								controls={false}
							/>
						</label>
						{usingSuggestion && (
							<small className="page-context">
								{suggestedRate.method === 'ai'
									? `ИИ подобрал из справочника: ${suggestedRate.name}`
									: 'Расценка из общего справочника'}
							</small>
						)}
						{notes && <p className="page-context">{notes}</p>}
						{editing && (!!editing.issues.length || editing.quantity_mode === 'mentions') && (
							<label>
								Как посчитать объём
								<Select
									value={resolution}
									onChange={(value) => {
										setResolution(value);
										if (value === 'sum' && editing.proposed_quantity !== null)
											setQuantity(String(editing.proposed_quantity));
										if (value === 'sum' || value === 'one') setUnit(editing.unit || unit);
										if (value === 'mentions') {
											setUnit(editing.unit || 'шт.');
											setQuantity(String(editing.mention_count ?? editing.sources.length));
										}
										if (value === 'one' && editing.sources[0]?.quantity != null)
											setQuantity(String(editing.sources[0].quantity));
									}}
									placeholder="Выберите решение"
									options={[
										{
											value: 'sum',
											label: `Сложить объёмы · ${editing.proposed_quantity ?? '—'} ${editing.unit || ''}`,
											disabled: editing.proposed_quantity === null,
										},
										{
											value: 'one',
											label: 'Повтор одной позиции — учесть один раз',
											disabled: editing.sources[0]?.quantity == null,
										},
										{
											value: 'mentions',
											label: `По упоминаниям · ${editing.mention_count ?? editing.sources.length}`,
											disabled:
												!editing.sources.length ||
												!['шт.', 'компл.'].includes(editing.unit || 'шт.'),
										},
										{ value: 'manual', label: 'Ввести объём вручную' },
									]}
								/>
							</label>
						)}
						{!!(
							job.payload.coverage?.drawings?.length ||
							job.payload.coverage?.low_ocr?.length ||
							job.payload.coverage?.questions
						) &&
							!job.payload.acknowledge_scope && (
								<Checkbox
									checked={acknowledge}
									onChange={(event) => setAcknowledge(event.target.checked)}
								>
									Источники и полнота проверены. Геометрия чертежей не измерялась.
								</Checkbox>
							)}
					</div>
				)}
			</Modal>
		</div>
	);
}
