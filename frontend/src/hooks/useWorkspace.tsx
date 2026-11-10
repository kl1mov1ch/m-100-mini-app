import { App as AntApp } from 'antd';
import 'dayjs/locale/ru';
import { useEffect, useRef, useState } from 'react';
import dayjs from '../lib/date';

import { headers, previewUser, request } from '../lib/api';
import { calculateAmount } from '../lib/calculation';
import { Money } from '../lib/format';
import { ReportConfirmation } from '../ReportConfirmation';
import type {
	Change,
	Config,
	Data,
	ImportPreview,
	ImportSheet,
	Line,
	Project,
	Report,
	Session,
	SpeechEngine,
	TableFixPayload,
	User,
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
	const [projectOpen, setProjectOpen] = useState(false),
		[objectForm, setObjectForm] = useState(false),
		[projectName, setProjectName] = useState(''),
		[projectOwner, setProjectOwner] = useState<string>(),
		[projectUrl, setProjectUrl] = useState(''),
		[projectFile, setProjectFile] = useState<number | null>(null),
		[sample, setSample] = useState(false);
	const [users, setUsers] = useState<User[]>([]),
		[userForm, setUserForm] = useState(false),
		[userId, setUserId] = useState(''),
		[userName, setUserName] = useState(''),
		[userRole, setUserRole] = useState('master'),
		[userEnabled, setUserEnabled] = useState(true);
	const [url, setUrl] = useState(''),
		[webhook, setWebhook] = useState(''),
		[fileId, setFileId] = useState<number | null>(null),
		[aiKey, setAiKey] = useState(''),
		[aiModel, setAiModel] = useState('deepseek-flash');
	const [changes, setChanges] = useState<Change[]>([]),
		[ownerFilter, setOwnerFilter] = useState('all'),
		[listening, setListening] = useState(false);
	const [summaryDate, setSummaryDate] = useState(dayjs().format('YYYY-MM-DD'));
	const [summaryProject, setSummaryProject] = useState('all');
	const speech = useRef<SpeechEngine | null>(null);
	const audioInput = useAudioInput(project, (transcript) =>
		setFreeText((current) => [current, transcript].filter(Boolean).join(' ')),
	);
	const [preview, setPreview] = useState<ImportPreview | null>(null),
		[ack, setAck] = useState<string[]>([]),
		[mapping, setMapping] = useState<ImportSheet[]>([]);
	const selectionVersion = useRef(0);
	const sessionVersion = useRef(0);
	const active = session?.projects.find((p) => p.id === project);
	const positions = data?.positions || [];
	const byId = Object.fromEntries(positions.map((p) => [p.id, p]));
	const isAdmin = session?.user.role === 'admin';
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
		await loadSession(selectedDate);
	};
	const loadData = async (id = project, keepEditor = false) => {
		const version = ++selectionVersion.current;
		const d = await request<Data>('/bootstrap', undefined, id);
		if (version !== selectionVersion.current) return;
		setData(d);
		setUrl(d.config.public_url);
		setFileId(d.config.file_id);
		if (!keepEditor) {
			const r =
				day === d.config.today ? d.report : await request<Report>('/report/' + day, undefined, id);
			if (version !== selectionVersion.current) return;
			setReport(r);
			setLines(r.lines);
			setCrew(r.crew_count);
			setReportText(r.text || '');
			if (d.config.pending_import) {
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
		if (!session?.projects.some((p) => p.id === project)) {
			setData(null);
			return;
		}
		setData(null);
		localStorage.setItem('selected-object' + (previewUser || ''), project);
		loadData().catch((e) => setFailure(e.message));
	}, [project, !!session]);
	useEffect(() => {
		if (!session) return;
		const timer = setInterval(() => {
			void loadSession().catch(() => {});
		}, 20000);
		return () => clearInterval(timer);
	}, [!!session, project, summaryDate]);
	useEffect(() => {
		if (!textOpen || freeText.trim().length < 5) {
			setParsed([]);
			return;
		}
		let stopped = false;
		setParsing(true);
		const timer = setTimeout(async () => {
			try {
				const r = await request<{ lines: Line[]; notice: string }>(
					'/parse',
					{ text: freeText },
					project,
				);
				if (!stopped) {
					setParsed(r.lines);
					setParseNote(r.notice);
				}
			} catch (e) {
				if (!stopped) setParseNote((e as Error).message);
			} finally {
				if (!stopped) setParsing(false);
			}
		}, 900);
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	}, [freeText, textOpen, project]);
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
		setPage('today');
		if (id !== project) setDay(selectedDay);
	};
	const openHistoryReport = (objectId: string, reportDay: string) => {
		if (objectId === project) void changeDay(reportDay);
		else {
			setDay(reportDay);
			setProject(objectId);
		}
		setPage('today');
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
	const telegramBack = userForm
		? () => setUserForm(false)
		: objectForm
			? () => setObjectForm(false)
			: preview
				? () => setPreview(null)
				: textOpen
					? () => {
							audioInput.stop();
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
		lines.length > 0 &&
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
	const confirm = () => {
		const exceeds = lines.some(
			(l) =>
				l.item_id && l.quantity! > (byId[l.item_id]?.remaining || 0) + (oldLines[l.item_id] || 0),
		);
		modal.confirm({
			title: 'Подтверждение отчёта',
			icon: null,
			width: 590,
			className: 'report-confirmation-modal',
			content: (
				<ReportConfirmation
					date={day}
					positions={byId}
					before={oldLines}
					after={nextLines}
					crewBefore={report?.crew_count || 1}
					crewAfter={crew}
					amountBefore={report?.payroll.amount || 0}
					amountAfter={amount}
					connected={!!data?.config.has_webhook && data?.config.source === 'bitrix'}
					exceeds={exceeds}
					renderMoney={(value) => <Money value={value} />}
				/>
			),
			okText: 'Подтвердить изменения',
			cancelText: 'Вернуться к отчёту',
			onOk: () => submit(exceeds),
		});
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
				public_url: projectUrl,
				file_id: projectFile,
				webhook: '',
				sample,
			});
			await loadSession();
			setProject(p.id);
			setObjectForm(false);
			setProjectName('');
			setProjectUrl('');
			setProjectFile(null);
			setSample(false);
			setPage('more');
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
				enabled: userEnabled,
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
	const switchSettingsProject = (objectId: string) => {
		setWebhook('');
		setProject(objectId);
	};
	const connect = async () => {
		if (data?.project?.id !== project) {
			message.info('Дождитесь загрузки выбранного объекта');
			return;
		}
		setBusy(true);
		try {
			await request('/bitrix/connection', { public_url: url, webhook, file_id: fileId }, project);
			setWebhook('');
			await refresh(true);
			message.success('Подключение сохранено');
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const importRemote = async () => {
		if (data?.project?.id !== project) {
			message.info('Дождитесь загрузки выбранного объекта');
			return;
		}
		setBusy(true);
		try {
			await request('/bitrix/connection', { public_url: url, webhook, file_id: fileId }, project);
			setWebhook('');
			const r = await request<ImportPreview>('/imports/bitrix', {}, project);
			if (!r.warnings.some((warning) => warning.severity !== 'info')) {
				await request(
					'/imports/confirm',
					{ token: r.token, sheets: r.sheets, acknowledged: [] },
					project,
				);
				await refresh(true);
				message.success('Таблица связана с объектом');
				return;
			}
			setPreview(r);
			setMapping(r.sheets);
			setAck([]);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const upload = async (file: File) => {
		setBusy(true);
		try {
			const form = new FormData();
			form.append('file', file);
			const r = await request<ImportPreview>('/imports/upload', form, project);
			setPreview(r);
			setMapping(r.sheets);
			setAck([]);
		} catch (e) {
			message.error((e as Error).message);
		} finally {
			setBusy(false);
		}
		return false;
	};
	const commitImport = async () => {
		if (!preview) return;
		setBusy(true);
		try {
			await request(
				'/imports/confirm',
				{ token: preview.token, sheets: mapping, acknowledged: ack },
				project,
			);
			setPreview(null);
			await refresh();
			message.success('Таблица готова к работе');
			setPage('more');
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
	const voice = () => {
		if (listening) {
			speech.current?.stop();
			return;
		}
		const Engine = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!Engine) {
			message.info('Голосовой ввод недоступен в этом браузере');
			return;
		}
		const r = new Engine();
		r.lang = 'ru-RU';
		r.onresult = (e) => setFreeText((t) => (t ? t + ' ' : '') + e.results[0][0].transcript);
		r.onend = () => setListening(false);
		r.onerror = () => {
			setListening(false);
			message.info('Проверьте доступ к микрофону');
		};
		speech.current = r;
		r.start();
		setListening(true);
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
			const r = await fetch('/api/export.csv', { headers: headers(project) });
			if (!r.ok) throw new Error('Не удалось выгрузить отчёт');
			const url = URL.createObjectURL(await r.blob());
			const link = document.createElement('a');
			link.href = url;
			link.download = 'Отчёты.csv';
			link.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			message.error((e as Error).message);
		}
	};
	return {
		openHistoryReport,
		checkingConnection,
		checkConnection,
		switchSettingsProject,
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
		setParsed,
		parsing,
		setParsing,
		parseNote,
		setParseNote,
		projectOpen,
		setProjectOpen,
		objectForm,
		setObjectForm,
		projectName,
		setProjectName,
		projectOwner,
		setProjectOwner,
		projectUrl,
		setProjectUrl,
		projectFile,
		setProjectFile,
		sample,
		setSample,
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
		userEnabled,
		setUserEnabled,
		url,
		setUrl,
		webhook,
		setWebhook,
		fileId,
		setFileId,
		aiKey,
		setAiKey,
		aiModel,
		setAiModel,
		changes,
		setChanges,
		ownerFilter,
		setOwnerFilter,
		listening,
		setListening,
		speech,
		preview,
		setPreview,
		ack,
		setAck,
		mapping,
		setMapping,
		selectionVersion,
		active,
		positions,
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
		retry,
		loadUsers,
		openSettings,
		createObject,
		grant,
		connect,
		importRemote,
		upload,
		commitImport,
		reviewImport,
		connectAI,
		voice,
		showChanges,
		exportCsv,
	};
}
