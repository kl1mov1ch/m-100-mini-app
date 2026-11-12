import { App, Button, Checkbox, Input, InputNumber, Modal, Pagination, Select, Tag } from 'antd';
import { ArrowLeft, ChevronRight, Download, FileSearch } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Money } from '../lib/format';
import { headers, request } from '../lib/api';
import { downloadReport } from '../lib/report-download';
import type { DocumentJob, DocumentGroup, DocumentSource } from './document-types';

function SourcePreview({
	jobId,
	page,
	highlights,
}: {
	jobId: string;
	page: number;
	highlights?: DocumentSource['highlights'];
}) {
	const [open, setOpen] = useState(false),
		[url, setUrl] = useState(''),
		[error, setError] = useState('');
	useEffect(() => {
		if (!open) return;
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
	}, [open, jobId, page]);
	return (
		<div className="document-page-preview">
			<Button type="link" onClick={() => setOpen(!open)}>
				{open ? 'Скрыть страницу' : 'Показать страницу PDF'}
			</Button>
			{open &&
				(error ? (
					<p>{error}</p>
				) : url ? (
					<div className="document-highlight-page">
						<a href={url} target="_blank" rel="noreferrer">
							<img src={url} alt={`Страница ${page} исходного PDF`} />
						</a>
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
				) : (
					<p>Загружаем страницу…</p>
				))}
		</div>
	);
}

export function DocumentResultsPage({
	job,
	back,
	refresh,
}: {
	job: DocumentJob;
	back: () => void;
	refresh: (job: DocumentJob) => void;
}) {
	const [category, setCategory] = useState('Все'),
		[status, setStatus] = useState('all'),
		[query, setQuery] = useState(''),
		[page, setPage] = useState(1),
		[editing, setEditing] = useState<DocumentGroup | null>(null),
		[sources, setSources] = useState<DocumentGroup | null>(null),
		[quantity, setQuantity] = useState<string | null>(null),
		[rate, setRate] = useState<string | null>(null),
		[unit, setUnit] = useState('м'),
		[name, setName] = useState(''),
		[editCategory, setEditCategory] = useState(''),
		[notes, setNotes] = useState(''),
		[resolution, setResolution] = useState<string>(),
		[acknowledge, setAcknowledge] = useState(false),
		[saving, setSaving] = useState(false),
		[rates, setRates] = useState<Record<string, string | null>>({});
	const { message } = App.useApp();
	const groups = job.payload.groups || [];
	const categories = ['Все', ...new Set(groups.map((row) => row.category))];
	const rows = groups.filter(
		(row) =>
			(category === 'Все' || row.category === category) &&
			(status === 'all' || (status === 'pending' ? !row.confirmed : row.confirmed)) &&
			row.name.toLowerCase().includes(query.toLowerCase()),
	);
	const summary = job.payload.summary;
	const needsScope = !!(
		job.payload.coverage?.drawings?.length ||
		job.payload.coverage?.low_ocr?.length ||
		job.payload.coverage?.questions
	);
	const eligible = rows
		.filter(
			(row) =>
				!row.confirmed && !row.issues.length && row.quantity !== null && rates[row.id] != null,
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
					rate: rates[row.id],
					unit: row.unit,
					notes: row.notes,
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
		setQuantity(row.quantity === null ? null : String(row.quantity));
		setRate(rates[row.id] ?? (row.rate === null ? null : String(row.rate)));
		setUnit(row.unit || 'м');
		setName(row.name);
		setEditCategory(row.category);
		setNotes(row.notes || '');
		setResolution(undefined);
		setAcknowledge(false);
	};
	const confirm = async () => {
		if (!editing || quantity === null || rate === null) return;
		setSaving(true);
		try {
			const next = await request<DocumentJob>('/documents/' + job.id + '/groups/' + editing.id, {
				version: job.updated_at,
				quantity,
				rate,
				unit,
				name,
				category: editCategory,
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
	const exportFile = async (final = false) => {
		try {
			await downloadReport('/documents/' + job.id + '/export.xlsx' + (final ? '?final=true' : ''));
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	return (
		<>
			<button className="back-link" onClick={back}>
				<ArrowLeft size={16} />
				Документы
			</button>
			<div className="page-title document-results-title">
				<div>
					<h1>Выборка работ</h1>
					<small className="page-context">{job.name}</small>
				</div>
			</div>
			<section className="document-result-summary">
				<p>{job.payload.query}</p>
				<div>
					<span>
						<small>Подтверждено</small>
						<strong>
							{summary?.confirmed || 0} / {groups.length}
						</strong>
					</span>
					<span>
						<small>Стоимость</small>
						<strong>
							<Money value={summary?.amount || 0} />
						</strong>
					</span>
				</div>
				<small>В сумме — только проверенные строки с расценками.</small>
			</section>
			<div className="document-notice">
				<strong>
					{job.processed} / {job.pages} страниц прочитано · {job.payload.analysis_done || 0} /{' '}
					{job.payload.analysis_total || 0} фрагментов разобрано
				</strong>
				{!job.payload.coverage?.complete && (
					<p>Обработка неполная — итоговый отчёт пока недоступен.</p>
				)}
				{needsScope && (
					<details>
						<summary>Проверить распознавание и полноту</summary>
						<p>
							Есть вопросы к полноте или качеству распознавания. Геометрические длины и площади по
							изображениям не измерялись. Проверьте источники отмеченных строк.
						</p>
					</details>
				)}
			</div>
			{!!job.payload.questions?.length && (
				<details className="document-questions">
					<summary>Вопросы по полноте · {job.payload.questions.length}</summary>
					<ul>
						{job.payload.questions.map((question, index) => (
							<li key={index}>{question}</li>
						))}
					</ul>
				</details>
			)}
			<div className="document-results-filters">
				<Input.Search
					placeholder="Найти работу"
					value={query}
					onChange={(event) => {
						setQuery(event.target.value);
						setPage(1);
					}}
				/>
				<div>
					<Select
						aria-label="Категория выборки"
						value={category}
						onChange={(value) => {
							setCategory(value);
							setPage(1);
						}}
						options={categories.map((value) => ({ value, label: value }))}
					/>
					<Select
						aria-label="Проверка строк"
						value={status}
						onChange={(value) => {
							setStatus(value);
							setPage(1);
						}}
						options={[
							{ value: 'all', label: 'Все строки' },
							{ value: 'pending', label: 'Требуют проверки' },
							{ value: 'confirmed', label: 'Подтверждены' },
						]}
					/>
				</div>
			</div>
			<div className="document-works">
				{rows.slice((page - 1) * 8, page * 8).map((row) => (
					<section
						className={'document-review-card' + (row.issues.length ? ' needs-review' : '')}
						key={row.id}
					>
						<div>
							<strong>{row.name}</strong>
							<Tag color={row.confirmed ? 'green' : undefined}>
								{row.confirmed ? 'Проверено' : row.issues.length ? 'Уточнить' : 'Черновик'}
							</Tag>
						</div>
						<small>
							{row.category} · {row.sources.length} источн.
						</small>
						<div className="document-review-values">
							<span>
								<small>Объём</small>
								<b>
									{row.quantity === null ? 'Нужна проверка' : row.quantity} {row.unit}
								</b>
							</span>
							<label className="document-inline-rate">
								<small>Расценка за {row.unit || 'единицу'}</small>
								{row.confirmed ? (
									<b>
										<Money value={Number(row.rate)} />
									</b>
								) : (
									<InputNumber
										stringMode
										controls={false}
										min="0"
										max="1000000000"
										precision={4}
										placeholder="BYN"
										aria-label={`Расценка: ${row.name}`}
										value={rates[row.id] ?? null}
										onChange={(value) => setRates((current) => ({ ...current, [row.id]: value }))}
									/>
								)}
							</label>
						</div>
						{row.notes && <p>{row.notes}</p>}
						{row.issues.length > 0 && <p className="document-question">{row.issues[0]}</p>}
						<div className="document-review-actions">
							<Button type="text" icon={<FileSearch size={16} />} onClick={() => setSources(row)}>
								Источники
							</Button>
							<Button type={row.confirmed ? 'default' : 'primary'} onClick={() => choose(row)}>
								{row.confirmed ? 'Изменить' : 'Расценка и проверка'}
								<ChevronRight size={15} />
							</Button>
						</div>
					</section>
				))}
			</div>
			{eligible.length > 0 && (
				<section className="document-batch-review">
					<small>
						Проверенные вами объёмы с введёнными расценками. Спорные строки подтверждаются отдельно.
					</small>
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
			{rows.length > 8 && (
				<Pagination
					simple={{ readOnly: true }}
					current={page}
					pageSize={8}
					total={rows.length}
					showSizeChanger={false}
					onChange={(value) => {
						setPage(value);
						window.scrollTo({ top: 0, behavior: 'smooth' });
					}}
				/>
			)}
			<div className="document-export-actions">
				<Button icon={<Download size={16} />} onClick={() => void exportFile()}>
					Excel-черновик
				</Button>
				<Button
					type="primary"
					disabled={job.status !== 'ready'}
					icon={<Download size={16} />}
					onClick={() => void exportFile(true)}
				>
					Итоговый отчёт
				</Button>
			</div>
			<Modal
				title={editing?.name}
				open={!!editing}
				onCancel={() => !saving && setEditing(null)}
				confirmLoading={saving}
				okText="Подтвердить позицию"
				cancelText="Отмена"
				onOk={() => void confirm()}
				okButtonProps={{
					disabled:
						quantity === null ||
						rate === null ||
						((editing?.issues.length || 0) > 0 && !resolution),
				}}
			>
				<div className="document-review-form">
					<label>
						Название работы
						<Input value={name} maxLength={300} onChange={(event) => setName(event.target.value)} />
					</label>
					<label>
						Категория
						<Select
							value={editCategory}
							onChange={setEditCategory}
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
					{editing?.issues.map((issue) => (
						<p className="document-question" key={issue}>
							{issue}
						</p>
					))}
					{editing && (
						<Button type="text" icon={<FileSearch size={16} />} onClick={() => setSources(editing)}>
							Проверить источники
						</Button>
					)}
					<label>
						Единица измерения
						<Select
							value={unit}
							onChange={setUnit}
							options={['м', 'м²', 'м³', 'шт.', 'кг', 'компл.', 'чел·ч', 'чел·дн'].map((value) => ({
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
							onChange={setQuantity}
							controls={false}
						/>
					</label>
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
					<label>
						Примечания
						<Input.TextArea
							value={notes}
							maxLength={2000}
							autoSize={{ minRows: 2, maxRows: 5 }}
							onChange={(event) => setNotes(event.target.value)}
						/>
					</label>
					{!!editing?.issues.length && (
						<label>
							Как проверен спорный объём
							<Select
								value={resolution}
								onChange={(value) => {
									setResolution(value);
									if (value === 'sum' && editing.proposed_quantity !== null)
										setQuantity(String(editing.proposed_quantity));
									if (value === 'one' && editing.sources[0]?.quantity !== null)
										setQuantity(String(editing.sources[0].quantity));
								}}
								placeholder="Выберите решение"
								options={[
									{
										value: 'sum',
										label: 'Работы разные — сложить объёмы',
										disabled: editing.proposed_quantity === null,
									},
									{
										value: 'one',
										label: 'Повтор одной позиции — учесть один раз',
										disabled: editing.sources[0]?.quantity === null,
									},
									{ value: 'manual', label: 'Объём проверен и уточнён вручную' },
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
								Подтверждаю полноту выборки с учётом вопросов и качества распознавания. Объёмы по
								геометрии чертежей не измерялись.
							</Checkbox>
						)}
				</div>
			</Modal>
			<Modal
				title="Источники позиции"
				open={!!sources}
				onCancel={() => setSources(null)}
				footer={<Button onClick={() => setSources(null)}>Понятно</Button>}
			>
				<div className="document-source">
					{sources?.sources.map((source, index) => (
						<section key={index}>
							<strong>
								Страница {source.page} · {source.original_quantity ?? 'Не определено'}{' '}
								{source.original_unit}
							</strong>
							<blockquote>{source.quote}</blockquote>
							{source.question && <p className="document-question">{source.question}</p>}
							<SourcePreview jobId={job.id} page={source.page} highlights={source.highlights} />
							{source.conversion_factor && source.conversion_factor !== '1' && (
								<p>
									Приведено к {source.unit}: {source.quantity}
								</p>
							)}
						</section>
					))}
				</div>
			</Modal>
		</>
	);
}
