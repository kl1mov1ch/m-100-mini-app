import { App as AntApp } from 'antd';
import 'dayjs/locale/ru';
import { createRef, useEffect, useRef, useState } from 'react';
import dayjs from '../lib/date';

import { previewUser, request } from '../lib/api';
import { calculateAmount, mergeWorkQuantities } from '../lib/calculation';
import { ReportReviewEditor, type ReportReviewHandle } from '../components/ReportReviewEditor';
import { Money } from '../lib/format';
import { downloadReport } from '../lib/report-download';
import { ReportConfirmation } from '../ReportConfirmation';
import type {
	Change,
	BitrixRead,
	Config,
	Data,
	ImportPreview,
	ImportSheet,
	Line,
	ObjectSection,
	Project,
	ParsedReport,
	Report,
	ReconciliationConfirmation,
	Session,
	TableFixPayload,
	User,
	ViewMode,
} from '../types';
import { useAudioInput } from './useAudioInput';
import { useTelegramNavigation } from './useTelegramNavigation';
export function useWorkspace() {
	const { message, modal } = AntApp.useApp();
	const [session, setSession] = useState<Session | null>(null),
		[data, setData] = useState<Data | null>(null),
		[failure, setFailure] = useState('');
	const [page, setPage] = useState(
			new URLSearchParams(location.search).has('object') ? 'today' : 'objects',
		),
		[project, setProject] = useState(
			new URLSearchParams(location.search).get('object') ||
				localStorage.getItem('selected-object' + (previewUser || '')) ||
				'default',
		),
		[busy, setBusy] = useState(false);
	const [objectSection, setObjectSection] = useState<ObjectSection>('reports');
	const [switchingRole, setSwitchingRole] = useState(false);
	const [readingBitrix, setReadingBitrix] = useState(false);
	const bitrixRead = useRef<AbortController | null>(null);
	const editorState = useRef({ project, day: '', dirty: false });
	const roleSwitch = useRef(false);
	const [day, setDay] = useState(dayjs().format('YYYY-MM-DD')),
		[report, setReport] = useState<Report | null>(null),
		[lines, setLines] = useState<Line[]>([]),
		[crew, setCrew] = useState(1),
		[reportText, setReportText] = useState('');
	const [workPicker, setWorkPicker] = useState(false),
		[replaceIndex, setReplaceIndex] = useState<number | null>(null),
		[textOpen, setTextOpen] = useState(false),
		[freeText, setFreeText] = useState(''),
		[parsed, setParsed] = useState<Line[]>([]),
		[parsing, setParsing] = useState(false),
		[parseNote, setParseNote] = useState('');
	const [parsedCrew, setParsedCrew] = useState<number | null>(null);
	const [parsedCrewAmbiguous, setParsedCrewAmbiguous] = useState(false);
	const parsedEditVersion = useRef(0);
	const matchRequest = useRef<AbortController | null>(null);
	const [projectOpen, setProjectOpen] = useState(false),
		[objectForm, setObjectForm] = useState(false),
		[projectName, setProjectName] = useState(''),
		[projectOwner, setProjectOwner] = useState<string>();
	const [users, setUsers] = useState<User[]>([]),
		[userForm, setUserForm] = useState(false),
		[userId, setUserId] = useState(''),
		[userName, setUserName] = useState(''),
		[userRole, setUserRole] = useState('master');
	const [url, setUrl] = useState(''),
		[webhook, setWebhook] = useState(''),
		[aiKey, setAiKey] = useState(''),
		[aiModel, setAiModel] = useState('deepseek-flash');
	const [changes, setChanges] = useState<Change[]>([]),
		[ownerFilter, setOwnerFilter] = useState('all');
	const [summaryDate, setSummaryDate] = useState(dayjs().format('YYYY-MM-DD'));
	const [summaryProject, setSummaryProject] = useState('all');
	const [preview, setPreview] = useState<ImportPreview | null>(null),
		[ack, setAck] = useState<string[]>([]),
		[mapping, setMapping] = useState<ImportSheet[]>([]);
	const selectionVersion = useRef(0);
	const sessionVersion = useRef(0);
	const active = session?.projects.find((p) => p.id === project);
	const allPositions = data?.project?.id === project ? data.positions : [];
	const positions = allPositions.filter((position) => !position.hidden);
	const byId = Object.fromEntries(allPositions.map((p) => [p.id, p]));
	const isAdmin = session?.user.role === 'admin';
	const audioInput = useAudioInput(
		project,
		JSON.stringify([day, page, isAdmin]),
		freeText,
		setFreeText,
	);
	const loadSession = async (selectedDate = summaryDate) => {
		const version = ++sessionVersion.current;
		const s = await request<Session>('/session?date=' + selectedDate);
		if (version !== sessionVersion.current) return s;
		setSession(s);
		if (!s.projects.some((p) => p.id === project) && s.projects[0]) setProject(s.projects[0].id);
		return s;
	};
	const changeSummaryDate = async (selectedDate: string) => {
		setSummaryDate(selectedDate);
		try {
			await loadSession(selectedDate);
		} catch (error) {
			setSummaryDate((current) =>
				current === selectedDate ? session?.selected_date || current : current,
			);
			message.error((error as Error).message);
		}
	};
	const changeViewMode = async (mode: ViewMode) => {
		if (!session?.can_switch_role || mode === session.view_mode || roleSwitch.current) return;
		roleSwitch.current = true;
		setSwitchingRole(true);
		const previousMode = localStorage.getItem('view-mode');
		localStorage.setItem('view-mode', mode);
		try {
			const next = await request<Session>('/session?date=' + session.today);
			if (next.view_mode !== mode) throw new Error('Этот режим недоступен');
			sessionVersion.current++;
			selectionVersion.current++;
			audioInput.cancel();
			setData(null);
			setReport(null);
			setLines([]);
			setReportText('');
			setCrew(1);
			setDay(next.today);
			setSummaryDate(next.today);
			setSummaryProject('all');
			setOwnerFilter('all');
			setObjectSection('reports');
			setPage('objects');
			if (!next.projects.some((item) => item.id === project)) {
				setProject(next.projects[0]?.id || 'default');
			}
			setSession(next);
		} catch (error) {
			if (previousMode) localStorage.setItem('view-mode', previousMode);
			else localStorage.removeItem('view-mode');
			message.error((error as Error).message);
		} finally {
			roleSwitch.current = false;
			setSwitchingRole(false);
		}
	};
	const loadData = async (id = project, keepEditor = false, onlyIfClean = false) => {
		const version = ++selectionVersion.current;
		const d = await request<Data>('/bootstrap', undefined, id);
		const r = keepEditor
			? null
			: day === d.config.today
				? d.report
				: await request<Report>('/report/' + day, undefined, id);
		if (version !== selectionVersion.current) return;
		setData(d);
		setUrl(d.config.public_url);
		if (r && (!onlyIfClean || (!editorState.current.dirty && editorState.current.day === day))) {
			setReport(r);
			setLines(r.lines);
			setCrew(r.crew_count);
			setReportText(r.text || '');
			if (!isAdmin && d.config.pending_import && !onlyIfClean) {
				const p = await request<ImportPreview>('/imports/pending', undefined, id);
				if (p && version === selectionVersion.current) {
					setPreview(p);
					setMapping(p.sheets);
					setAck([]);
				}
			}
		}
	};
	useEffect(() => {
		window.Telegram?.WebApp?.ready();
		loadSession().catch((e) => setFailure(e.message));
	}, []);
	useEffect(() => {
		selectionVersion.current++;
		setPreview(null);
		setTextOpen(false);
		setFreeText('');
		setWebhook('');
		if (!session?.projects.some((p) => p.id === project)) {
			setData(null);
			return;
		}
		setData(null);
		localStorage.setItem('selected-object' + (previewUser || ''), project);
		loadData().catch((e) => setFailure(e.message));
	}, [project, session?.user.role]);
	useEffect(() => {
		if (!session) return;
		const timer = setInterval(() => {
			if (!roleSwitch.current) void loadSession().catch(() => {});
		}, 20000);
		return () => clearInterval(timer);
	}, [!!session, project, summaryDate]);
	useEffect(() => {
		setParsed([]);
		setParsedCrew(null);
		setParsedCrewAmbiguous(false);
		setParseNote('');
		setParsing(false);
		return () => {
			matchRequest.current?.abort();
			matchRequest.current = null;
		};
	}, [freeText, project, day, page, isAdmin]);

	const matchReportText = async () => {
		const text = freeText.trim();
		if (!text || isAdmin || !active || !positions.length || matchRequest.current) return;
		if (audioInput.recording || audioInput.pending) return;
		const controller = new AbortController();
		matchRequest.current = controller;
		setParsed([]);
		setParsedCrew(null);
		setParsedCrewAmbiguous(false);
		setParsing(true);
		setParseNote('');
		parsedEditVersion.current = 0;
		const apply = (result: ParsedReport) => {
			setParsed(result.lines);
			setParsedCrew(result.crew_count);
			setParsedCrewAmbiguous(result.crew_ambiguous);
			setParseNote(
				result.lines.length ? '' : 'Работы не найдены. Уточните название и объём в сообщении.',
			);
		};
		try {
			const local = await request<ParsedReport>(
				'/parse',
				{ text, local_only: true },
				project,
				controller.signal,
			);
			if (controller.signal.aborted) return;
			apply(local);
			if (local.needs_ai && session?.ai_connected) {
				const improved = await request<ParsedReport>(
					'/parse',
					{ text },
					project,
					controller.signal,
				);
				if (!controller.signal.aborted && parsedEditVersion.current === 0) apply(improved);
			}
		} catch (error) {
			if (!controller.signal.aborted) setParseNote((error as Error).message);
		} finally {
			if (matchRequest.current === controller) {
				matchRequest.current = null;
				setParsing(false);
			}
		}
	};
	const refresh = async (keep = false) => {
		await Promise.all([loadSession(), ...(active ? [loadData(project, keep)] : [])]);
	};
	const changeDay = async (value: string) => {
		const version = ++selectionVersion.current;
		try {
			const r = await request<Report>('/report/' + value, undefined, project);
			if (version !== selectionVersion.current) return;
			setDay(value);
			setReport(r);
			setLines(r.lines);
			setCrew(r.crew_count);
			setReportText(r.text || '');
		} catch (e) {
			message.error((e as Error).message);
		}
	};
	const selectObject = (id: string) => {
		const selectedDay = isAdmin ? summaryDate : session?.today || day;
		setParsed([]);
		if (id === project) void changeDay(selectedDay);
		setProject(id);
		setProjectOpen(false);
		setObjectSection('reports');
		setPage(isAdmin ? 'today' : 'object');
		if (id !== project) setDay(selectedDay);
	};
	const openHistoryReport = (objectId: string, reportDay: string) => {
		if (objectId === project) void changeDay(reportDay);
		else {
			setDay(reportDay);
			setProject(objectId);
		}
		setObjectSection('reports');
		setPage('today');
	};
	const openObjectSection = (section: ObjectSection) => {
		setObjectSection(section);
		setPage('object');
	};
	const addLine = (id: string) => {
		if (replaceIndex !== null)
			setLines((ls) => ls.map((l, i) => (i === replaceIndex ? { ...l, item_id: id } : l)));
		else if (!lines.some((l) => l.item_id === id))
			setLines((ls) => [...ls, { item_id: id, quantity: null }]);
		setReplaceIndex(null);
		setWorkPicker(false);
	};
	const patchLine = (index: number, quantity: number | null) =>
		setLines((ls) => ls.map((l, i) => (i === index ? { ...l, quantity } : l)));
	const amount = calculateAmount(
		lines.map((line) => ({
			quantity: line.quantity,
			rate: line.item_id ? byId[line.item_id]?.rate || 0 : 0,
		})),
	);
	const cents = Math.round(amount * 100),
		each = Math.floor(cents / crew) / 100,
		extra = cents % crew;
	const oldLines = Object.fromEntries((report?.lines || []).map((l) => [l.item_id, l.quantity]));
	const nextLines = Object.fromEntries(lines.map((l) => [l.item_id, l.quantity]));
	const deltaIds = [...new Set([...Object.keys(oldLines), ...Object.keys(nextLines)])].filter(
		(id) => oldLines[id] !== nextLines[id],
	);
	const dirty = deltaIds.length > 0 || crew !== report?.crew_count || reportText !== report?.text;
	editorState.current = { project, day, dirty: !!report && dirty };
	const refreshBitrix = async (force = false) => {
		if (
			isAdmin ||
			data?.project?.id !== project ||
			data.config.source !== 'bitrix' ||
			bitrixRead.current
		)
			return;
		const controller = new AbortController();
		const selection = selectionVersion.current;
		bitrixRead.current = controller;
		setReadingBitrix(true);
		try {
			const updated = await request<BitrixRead | null>(
				'/bitrix/refresh' + (force ? '?force=true' : ''),
				{},
				project,
				controller.signal,
			);
			if (
				!controller.signal.aborted &&
				selection === selectionVersion.current &&
				editorState.current.project === project &&
				updated &&
				updated.checked_at !== data.config.bitrix_read?.checked_at
			) {
				await loadData(project, editorState.current.dirty || editorState.current.day !== day, true);
			}
		} catch (error) {
			if (force && !controller.signal.aborted) message.error((error as Error).message);
		} finally {
			if (bitrixRead.current === controller) {
				bitrixRead.current = null;
				setReadingBitrix(false);
			}
		}
	};
	useEffect(() => {
		setReadingBitrix(false);
		return () => {
			bitrixRead.current?.abort();
			bitrixRead.current = null;
		};
	}, [project, isAdmin]);
	useEffect(() => {
		if (page === 'today' || page === 'object' || page === 'objects') void refreshBitrix();
	}, [
		project,
		page,
		objectSection,
		data?.config.source,
		data?.config.last_import,
		workPicker,
		textOpen,
		isAdmin,
	]);
	const telegramBack = userForm
		? () => setUserForm(false)
		: objectForm
			? () => setObjectForm(false)
			: preview
				? () => setPreview(null)
				: textOpen
					? () => {
							audioInput.cancel();
							setTextOpen(false);
						}
					: workPicker
						? () => {
								setWorkPicker(false);
								setReplaceIndex(null);
							}
						: projectOpen
							? () => setProjectOpen(false)
							: page !== 'objects'
								? () => setPage('objects')
								: undefined;
	useTelegramNavigation(telegramBack, (!!report && dirty) || (textOpen && !!freeText.trim()));
	const valid =
		(lines.length > 0 || !!report?.lines.length) &&
		lines.every((l) => l.item_id && l.quantity !== null && l.quantity > 0) &&
		new Set(lines.map((l) => l.item_id)).size === lines.length;
	const submit = async (allow = false) => {
		if (!report) return;
		setBusy(true);
		try {
			const r = await request<Report>(
				'/reports',
				{
					date: day,
					revision: report.revision,
					lines: lines.map((l) => ({
						item_id: l.item_id,
						quantity: l.quantity,
					})),
					crew_count: crew,
					text: reportText,
					allow_exceed: allow,
				},
				project,
			);
			setReport(r);
			setLines(r.lines);
			if (r.changed === false) message.info('Изменений нет');
			else if (r.sync_status === 'synced')
				message.success('Отчёт подтверждён и записан в Битрикс24');
			else message.info('Отчёт подтверждён. ' + (r.sync_error || 'Ожидает отправки'));
			await refresh(true);
			window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred('success');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const openReportReview = (
		next: { item_id: string; quantity: number }[],
		nextCrew: number,
		nextText: string,
		freeform = false,
	) => {
		if (!report) return;
		const editor = createRef<ReportReviewHandle>();
		const reviewModal = modal.confirm({
			title: 'Общий отчёт за день',
			icon: null,
			width: 620,
			className: 'report-confirmation-modal',
			content: (
				<ReportReviewEditor
					ref={editor}
					report={report}
					positions={byId}
					lines={next}
					crew={nextCrew}
					connected={!!data?.config.has_webhook && data?.config.source === 'bitrix'}
					onValidityChange={(valid) => reviewModal.update({ okButtonProps: { disabled: !valid } })}
				/>
			),
			okText: 'Подтвердить и отправить',
			cancelText: 'Вернуться',
			onOk: async () => {
				if (editorState.current.project !== project || editorState.current.day !== day)
					throw new Error('Выбран другой объект. Проверьте отчёт заново.');
				const values = editor.current?.getValues();
				if (!values) throw new Error('Дождитесь открытия отчёта');
				const exceeds = values.lines.some(
					(line) => line.quantity > byId[line.item_id].remaining + (oldLines[line.item_id] || 0),
				);
				setBusy(true);
				parsedEditVersion.current++;
				try {
					const saved = await request<Report>(
						'/reports',
						{
							date: day,
							revision: report.revision,
							...values,
							text: nextText,
							allow_exceed: exceeds,
						},
						project,
					);
					setReport(saved);
					setLines(saved.lines);
					setCrew(saved.crew_count);
					setReportText(saved.text || '');
					if (freeform) {
						setTextOpen(false);
						setFreeText('');
					}
					await refresh(true);
					if (saved.sync_status === 'synced')
						message.success('Готово. Отчёт и расчёты записаны в Битрикс24');
					else message.info('Отчёт сохранён. ' + (saved.sync_error || 'Ожидает отправки'));
					window.Telegram?.WebApp?.HapticFeedback?.notificationOccurred('success');
				} catch (error) {
					message.error((error as Error).message);
					throw error;
				} finally {
					setBusy(false);
				}
			},
		});
	};
	const confirm = () =>
		openReportReview(
			lines.map((line) => ({ item_id: line.item_id!, quantity: line.quantity! })),
			crew,
			reportText,
		);
	const patchParsedLine = (index: number, patch: Partial<Line>) => {
		parsedEditVersion.current++;
		setParsed((current) =>
			current.map((line, lineIndex) => (lineIndex === index ? { ...line, ...patch } : line)),
		);
	};
	const removeParsedLine = (index: number) => {
		parsedEditVersion.current++;
		setParsed((current) => current.filter((_, lineIndex) => lineIndex !== index));
	};
	const updateParsedCrew = (count: number | null) => {
		parsedEditVersion.current++;
		setParsedCrew(count);
		setParsedCrewAmbiguous(false);
	};
	const confirmParsedReport = () => {
		if (!report || !parsed.length || parsedCrewAmbiguous) {
			message.warning(
				parsedCrewAmbiguous ? 'Уточните количество работников' : 'Добавьте выполненные работы',
			);
			return;
		}
		const combined = [...lines, ...parsed];
		if (
			combined.some(
				(line) => !line.item_id || !byId[line.item_id] || !line.quantity || line.quantity <= 0,
			)
		) {
			message.warning('Проверьте выделенные работы и объёмы');
			return;
		}
		const next = mergeWorkQuantities(
			combined.map((line) => ({ item_id: line.item_id!, quantity: line.quantity! })),
		);
		openReportReview(
			next,
			parsedCrew || crew,
			[reportText, freeText].filter(Boolean).join('\n'),
			true,
		);
	};
	const retry = async (date: string) => {
		setBusy(true);
		try {
			const r = await request<{ ok: boolean; message?: string }>(
				'/bitrix/sync/' + date,
				{},
				project,
			);
			r.ok ? message.success('Изменения отправлены') : message.warning(r.message);
			await refresh(true);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const restoreDay = async () => {
		if (!report) return;
		try {
			const preview = await request<{ current: Report; target: Report }>(
				'/report/' + day + '/restore-preview',
				undefined,
				project,
			);
			const version = selectionVersion.current;
			const restoredLines = Object.fromEntries(
				preview.target.lines.map((line) => [line.item_id, line.quantity]),
			);
			modal.confirm({
				title: 'Вернуть отчёт к началу дня?',
				icon: null,
				width: 590,
				className: 'report-confirmation-modal',
				content: (
					<>
						<p>
							Восстановится состояние до первого подтверждения за {dayjs(day).format('D MMMM YYYY')}
							. Изменения останутся в истории. Другие дни сохранятся.
						</p>
						<ReportConfirmation
							date={day}
							positions={byId}
							before={Object.fromEntries(
								preview.current.lines.map((line) => [line.item_id, line.quantity]),
							)}
							after={restoredLines}
							crewBefore={preview.current.crew_count}
							crewAfter={preview.target.crew_count}
							amountBefore={preview.current.payroll.amount}
							amountAfter={preview.target.payroll.amount}
							connected={!!data?.config.has_webhook && data?.config.source === 'bitrix'}
							exceeds={false}
							renderMoney={(value) => <Money value={value} />}
						/>
					</>
				),
				okText: 'Восстановить и отправить',
				cancelText: 'Оставить как есть',
				onOk: async () => {
					if (version !== selectionVersion.current)
						throw new Error('Выбран другой отчёт. Откройте восстановление заново.');
					setBusy(true);
					try {
						const restored = await request<Report>(
							'/report/' + day + '/restore',
							{ revision: preview.current.revision },
							project,
						);
						setReport(restored);
						setLines(restored.lines);
						setCrew(restored.crew_count);
						setReportText(restored.text || '');
						await refresh(true);
						if (restored.sync_status === 'synced')
							message.success('Отчёт восстановлен, расчёты обновлены в Битрикс24');
						else
							message.warning(
								'Отчёт восстановлен. ' + (restored.sync_error || 'Ожидает отправки в Битрикс24'),
							);
					} catch (error) {
						message.error((error as Error).message);
						throw error;
					} finally {
						setBusy(false);
					}
				},
			});
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	const loadUsers = async () => {
		try {
			setUsers(await request<User[]>('/admin/users'));
		} catch (e) {
			message.error((e as Error).message);
		}
	};
	const openSettings = () => {
		setPage('more');
		if (isAdmin) void loadUsers();
	};
	const createObject = async () => {
		setBusy(true);
		try {
			const p = await request<Project>('/projects', {
				name: projectName,
				owner_id: projectOwner || session?.user.telegram_id,
			});
			await loadSession();
			setProject(p.id);
			setObjectForm(false);
			setProjectName('');
			if (isAdmin) setPage('objects');
			else {
				setDay(session?.today || day);
				openObjectSection('table');
			}
			message.success('Объект добавлен');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const grant = async () => {
		setBusy(true);
		try {
			await request('/admin/users', {
				telegram_id: userId,
				name: userName,
				role: userRole,
			});
			setUserForm(false);
			await loadUsers();
			message.success('Доступ обновлён');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const [checkingConnection, setCheckingConnection] = useState(false);
	const checkConnection = async () => {
		setCheckingConnection(true);
		try {
			const result = await request<NonNullable<Config['connection_check']>>(
				'/bitrix/check',
				{},
				project,
			);
			await loadData(project, true);
			if (result.reachable) message.success(result.message);
			else message.error(result.message);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setCheckingConnection(false);
		}
	};
	const loadRemoteImport = async (reviewOnly: boolean) => {
		if (data?.project?.id !== project) {
			message.info('Дождитесь загрузки выбранного объекта');
			return;
		}
		setBusy(true);
		const selection = selectionVersion.current;
		try {
			if (!reviewOnly) {
				await request('/bitrix/connection', { public_url: url, webhook }, project);
				setWebhook('');
			}
			const r = await request<ImportPreview>('/imports/bitrix', {}, project);
			if (selection !== selectionVersion.current) return;
			if (
				!reviewOnly &&
				!r.warnings.some((warning) => warning.severity !== 'info') &&
				!r.reconciliation?.needs_confirmation
			) {
				await request(
					'/imports/confirm',
					{ token: r.token, sheets: r.sheets, acknowledged: [] },
					project,
				);
				if (selection !== selectionVersion.current) return;
				await refresh(true);
				message.success('Таблица связана с объектом');
				return;
			}
			setPreview(r);
			setMapping(r.sheets);
			setAck([]);
			await loadData(project, true);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const importRemote = () => loadRemoteImport(false);
	const upload = async (file: File) => {
		setBusy(true);
		const selection = selectionVersion.current;
		try {
			const form = new FormData();
			form.append('file', file);
			const r = await request<ImportPreview>('/imports/upload', form, project);
			if (selection !== selectionVersion.current) return false;
			setPreview(r);
			setMapping(r.sheets);
			setAck([]);
			await loadData(project, true);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
		return false;
	};
	const resumeImport = async () => {
		setBusy(true);
		const selection = selectionVersion.current;
		try {
			const pending = await request<ImportPreview | null>('/imports/pending', undefined, project);
			if (selection !== selectionVersion.current) return;
			if (!pending) {
				await loadData(project, true);
				return;
			}
			setPreview(pending);
			setMapping(pending.sheets);
			setAck([]);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const commitImport = async (reconciliation?: ReconciliationConfirmation) => {
		if (!preview) return;
		setBusy(true);
		try {
			await request(
				'/imports/confirm',
				{ token: preview.token, sheets: mapping, acknowledged: ack, ...reconciliation },
				project,
			);
			setPreview(null);
			await refresh();
			message.success('Таблица готова к работе');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const reviewImport = async () => {
		if (!preview) return;
		setBusy(true);
		try {
			const r = await request<ImportPreview>(
				'/imports/review',
				{ token: preview.token, sheets: mapping, acknowledged: ack },
				project,
			);
			setPreview(r);
			setMapping(r.sheets);
			setAck([]);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const applyImportChanges = async (changes: TableFixPayload) => {
		if (!preview) return;
		setBusy(true);
		try {
			const updated = await request<ImportPreview & { saved_to_source: boolean }>(
				'/imports/edit',
				{ token: preview.token, ...changes },
				project,
			);
			setPreview(updated);
			setMapping(updated.sheets);
			setAck([]);
			message.success(
				updated.saved_to_source
					? 'Исправления сохранены и проверены в Битрикс24'
					: 'Исправления внесены в загруженный файл',
			);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const connectAI = async () => {
		setBusy(true);
		try {
			await request('/ai/connection', {
				api_key: aiKey,
				base_url: 'https://api.deepseek.com',
				model: aiModel,
			});
			setAiKey('');
			await refresh(true);
			message.success('DeepSeek подключён');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const showChanges = async () => {
		try {
			setChanges(await request<Change[]>('/changes', undefined, project));
			setPage('changes');
		} catch (e) {
			message.error((e as Error).message);
		}
	};
	const exportCsv = async () => {
		try {
			await downloadReport('/export.csv', project);
		} catch (e) {
			message.error((e as Error).message);
		}
	};
	return {
		openHistoryReport,
		checkingConnection,
		checkConnection,
		refreshBitrix,
		readingBitrix,
		objectSection,
		openObjectSection,
		switchingRole,
		changeViewMode,
		resumeImport,
		applyImportChanges,
		summaryDate,
		setSummaryDate,
		summaryProject,
		setSummaryProject,
		changeSummaryDate,
		audioInput,
		session,
		setSession,
		data,
		setData,
		failure,
		setFailure,
		page,
		setPage,
		project,
		setProject,
		busy,
		setBusy,
		day,
		setDay,
		report,
		setReport,
		lines,
		setLines,
		crew,
		setCrew,
		reportText,
		setReportText,
		workPicker,
		setWorkPicker,
		replaceIndex,
		setReplaceIndex,
		textOpen,
		setTextOpen,
		freeText,
		setFreeText,
		parsed,
		parsedCrew,
		parsedCrewAmbiguous,
		patchParsedLine,
		removeParsedLine,
		updateParsedCrew,
		confirmParsedReport,
		matchReportText,
		parsing,
		parseNote,
		projectOpen,
		setProjectOpen,
		objectForm,
		setObjectForm,
		projectName,
		setProjectName,
		projectOwner,
		setProjectOwner,
		users,
		setUsers,
		userForm,
		setUserForm,
		userId,
		setUserId,
		userName,
		setUserName,
		userRole,
		setUserRole,
		url,
		setUrl,
		webhook,
		setWebhook,
		aiKey,
		setAiKey,
		aiModel,
		setAiModel,
		changes,
		setChanges,
		ownerFilter,
		setOwnerFilter,
		preview,
		setPreview,
		ack,
		setAck,
		mapping,
		setMapping,
		selectionVersion,
		active,
		positions,
		allPositions,
		byId,
		isAdmin,
		loadSession,
		loadData,
		refresh,
		changeDay,
		selectObject,
		addLine,
		patchLine,
		amount,
		cents,
		each,
		extra,
		oldLines,
		nextLines,
		deltaIds,
		dirty,
		valid,
		submit,
		confirm,
		restoreDay,
		retry,
		loadUsers,
		openSettings,
		createObject,
		grant,
		importRemote,
		reviewBitrixChanges: () =>
			data?.config.pending_import ? resumeImport() : loadRemoteImport(true),
		upload,
		commitImport,
		reviewImport,
		connectAI,
		showChanges,
		exportCsv,
	};
}
