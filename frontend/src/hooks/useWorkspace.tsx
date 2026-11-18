import { confirmSheet } from '../components/SheetModal';
import { App as AntApp } from 'antd';
import 'dayjs/locale/ru';
import { createRef, useEffect, useEffectEvent, useRef, useState } from 'react';
import dayjs from '../lib/date';

import { previewUser, request, RequestError } from '../lib/api';
import { calculateAmount, mergeWorkQuantities } from '../lib/calculation';
import { ReportReviewEditor, type ReportReviewHandle } from '../components/ReportReviewEditor';
import { Money } from '../lib/format';
import {
	pruneFormDrafts,
	readFormDraft,
	removeFormDraft,
	writeFormDraft,
} from '../lib/form-drafts';
import { downloadReport } from '../lib/report-download';
import { ReportConfirmation } from '../ReportConfirmation';
import { estimateBalance } from '../lib/position-volume';
import { takeReleaseNavigation } from './useAppRelease';
import type {
	Change,
	BitrixRead,
	Config,
	Data,
	DiskWebhook,
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

type ReportDraft = {
	revision: number;
	lines: Line[];
	crew: number;
	text: string;
	note: string;
};

type MemberDraft = { id: string; name: string; role: string };

export function useWorkspace() {
	const { message, modal } = AntApp.useApp();
	const [releaseNavigation] = useState(takeReleaseNavigation);
	const [session, setSession] = useState<Session | null>(null),
		[data, setData] = useState<Data | null>(null),
		[failure, setFailure] = useState<Error | null>(null);
	const [page, setPage] = useState(
			(releaseNavigation?.page !== 'documents' && releaseNavigation?.page) ||
				(new URLSearchParams(location.search).has('object') ? 'today' : 'objects'),
		),
		[project, setProject] = useState(
			releaseNavigation?.project ||
				new URLSearchParams(location.search).get('object') ||
				localStorage.getItem('selected-object' + (previewUser || '')) ||
				'default',
		),
		[busy, setBusy] = useState(false);
	const [objectSection, setObjectSection] = useState<ObjectSection>(
		releaseNavigation?.objectSection || 'reports',
	);
	const [switchingRole, setSwitchingRole] = useState(false);
	const [readingBitrix, setReadingBitrix] = useState(false);
	const bitrixRead = useRef<AbortController | null>(null);
	const editorState = useRef({ project, day: '', dirty: false });
	const roleSwitch = useRef(false);
	const [day, setDay] = useState(releaseNavigation?.day || dayjs().format('YYYY-MM-DD')),
		[report, setReport] = useState<Report | null>(null),
		[estimateReport, setEstimateReport] = useState<Report | null>(null),
		[lines, setLines] = useState<Line[]>([]),
		[crew, setCrew] = useState(1),
		[reportText, setReportText] = useState(''),
		[dayNote, setDayNote] = useState('');
	const [workPicker, setWorkPicker] = useState(false),
		[replaceIndex, setReplaceIndex] = useState<number | null>(null),
		[textOpen, setTextOpen] = useState(false),
		[freeText, setFreeText] = useState(''),
		[parsed, setParsed] = useState<Line[]>([]),
		[parsing, setParsing] = useState(false),
		[parseNote, setParseNote] = useState('');
	const [parsedCrewAmbiguous, setParsedCrewAmbiguous] = useState(false);
	const parsedEditVersion = useRef(0);
	const matchRequest = useRef<AbortController | null>(null);
	const [projectOpen, setProjectOpen] = useState(false),
		[objectForm, setObjectFormOpen] = useState(false),
		[projectName, setProjectName] = useState(''),
		[projectOwner, setProjectOwner] = useState<string>();
	const [users, setUsers] = useState<User[]>([]),
		[userForm, setUserForm] = useState(false),
		[userId, setUserId] = useState(''),
		[userName, setUserName] = useState(''),
		[userRole, setUserRole] = useState('master');
	const [editingUser, setEditingUser] = useState<string | null>(null);
	const reportEditorKey = useRef<string | null>(null);
	const [url, setUrl] = useState(''),
		[webhookId, setWebhookId] = useState<string>(),
		[aiKey, setAiKey] = useState(''),
		[aiModel, setAiModel] = useState('deepseek-flash');
	const [diskWebhooks, setDiskWebhooks] = useState<DiskWebhook[]>([]);
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
	const openProjectId = (page === 'object' || page === 'today') && active ? active.id : null;
	const sessionUserId = session?.user.telegram_id;
	useEffect(() => {
		if (!sessionUserId) return;
		const controller = new AbortController();
		const publish = () => {
			if (document.visibilityState !== 'visible') return;
			void request(
				'/session/open-project',
				{ project_id: openProjectId },
				undefined,
				controller.signal,
			).catch(() => {});
		};
		publish();
		const timer = window.setInterval(publish, 25000);
		document.addEventListener('visibilitychange', publish);
		return () => {
			controller.abort();
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', publish);
		};
	}, [openProjectId, sessionUserId, session?.user.role]);
	const allPositions = data?.project?.id === project ? data.positions : [];
	const positions = allPositions.filter((position) => !position.hidden && !position.extra);
	const byId = Object.fromEntries(allPositions.map((p) => [p.id, p]));
	const isAdmin = session?.user.role === 'admin';
	const quickDraftKey =
		sessionUserId && !isAdmin ? `quick:${sessionUserId}:${project}:${day}` : null;
	const [loadedQuickDraft, setLoadedQuickDraft] = useState<string | null>(null);
	useEffect(() => {
		setFreeText(quickDraftKey ? (readFormDraft<string>(quickDraftKey) ?? '') : '');
		setLoadedQuickDraft(quickDraftKey);
	}, [quickDraftKey]);
	useEffect(() => {
		if (!quickDraftKey || loadedQuickDraft !== quickDraftKey) return;
		if (freeText) writeFormDraft(quickDraftKey, freeText);
		else removeFormDraft(quickDraftKey);
	}, [quickDraftKey, loadedQuickDraft, freeText]);
	const memberDraftKey = `member:${sessionUserId}:${editingUser || 'new'}`;
	const objectDraftKey = `object:${sessionUserId}:${session?.user.role}`;
	const setObjectForm = (open: boolean) => {
		if (open && sessionUserId) {
			const draft = readFormDraft<{ name: string; owner?: string }>(objectDraftKey);
			setProjectName(draft?.name ?? '');
			setProjectOwner(draft?.owner);
		}
		setObjectFormOpen(open);
	};
	const reportKey = (id: string, date: string) => `report:${sessionUserId}:${id}:${date}`;
	const openUserForm = (user?: User) => {
		const draft = readFormDraft<MemberDraft>(
			`member:${sessionUserId}:${user?.telegram_id || 'new'}`,
		);
		setEditingUser(user?.telegram_id ?? null);
		setUserId(user?.telegram_id ?? draft?.id ?? '');
		setUserName(draft?.name ?? user?.name ?? '');
		setUserRole(draft?.role ?? user?.role ?? 'master');
		setUserForm(true);
	};
	useEffect(() => {
		pruneFormDrafts();
		const timer = window.setInterval(pruneFormDrafts, 60 * 60 * 1000);
		return () => window.clearInterval(timer);
	}, []);
	useEffect(() => {
		if (sessionUserId && objectForm)
			writeFormDraft(objectDraftKey, { name: projectName, owner: projectOwner });
	}, [sessionUserId, objectDraftKey, objectForm, projectName, projectOwner]);
	useEffect(() => {
		if (sessionUserId && isAdmin && userForm)
			writeFormDraft(memberDraftKey, { id: userId, name: userName, role: userRole });
	}, [sessionUserId, isAdmin, userForm, memberDraftKey, userId, userName, userRole]);

	const loadReportEditor = (id: string, saved: Report) => {
		const key = reportKey(id, saved.date);
		const draft = sessionUserId && !isAdmin ? readFormDraft<ReportDraft>(key) : undefined;
		const restored = draft?.revision === saved.revision ? draft : undefined;
		reportEditorKey.current = key;
		setReport(saved);
		setLines(restored?.lines ?? saved.lines);
		setCrew(restored?.crew ?? saved.crew_count);
		setReportText(restored?.text ?? saved.text ?? '');
		setDayNote(restored?.note ?? saved.day_note ?? '');
	};
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
			setDayNote('');
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
		const r =
			day === d.config.today
				? d.report
				: keepEditor && !onlyIfClean
					? null
					: await request<Report>('/report/' + day, undefined, id);
		if (version !== selectionVersion.current) return;
		setData(d);
		if (!onlyIfClean) setUrl(d.config.public_url);
		if (r) setEstimateReport(r);
		if (
			!keepEditor &&
			r &&
			(!onlyIfClean || (!editorState.current.dirty && editorState.current.day === day))
		) {
			loadReportEditor(id, r);
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
		loadSession().catch(setFailure);
	}, []);
	useEffect(() => {
		setDiskWebhooks([]);
		if (session?.user.role !== 'master') return;
		const controller = new AbortController();
		request<DiskWebhook[]>('/profile/disk-webhooks', undefined, undefined, controller.signal)
			.then((items) => {
				if (!controller.signal.aborted) setDiskWebhooks(items);
			})
			.catch((error: Error) => {
				if (!controller.signal.aborted) message.error(error.message);
			});
		return () => controller.abort();
	}, [session?.user.role, session?.user.telegram_id]);
	useEffect(() => {
		selectionVersion.current++;
		setPreview(null);
		setTextOpen(false);
		setWebhookId(undefined);
		if (!session?.projects.some((p) => p.id === project)) {
			setData(null);
			return;
		}
		setData(null);
		setEstimateReport(null);
		localStorage.setItem('selected-object' + (previewUser || ''), project);
		loadData().catch(setFailure);
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
		setParsedCrewAmbiguous(false);
		setParsing(true);
		setParseNote('');
		parsedEditVersion.current = 0;
		const apply = (result: ParsedReport) => {
			setParsed(result.lines);
			if (result.crew_count != null && !result.crew_ambiguous) setCrew(result.crew_count);
			setParsedCrewAmbiguous(result.crew_ambiguous);
			setParseNote(
				result.lines.length || result.crew_count != null || result.crew_ambiguous
					? ''
					: 'Работы не найдены. Уточните название и объём в сообщении.',
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
			setEstimateReport(r);
			loadReportEditor(project, r);
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
	const selectQuickReportProject = (id: string) => {
		if (isAdmin || !session?.projects.some((item) => item.id === id)) return;
		if (id !== project) {
			matchRequest.current?.abort();
			audioInput.cancel();
			setFreeText('');
			setParsed([]);
			setDay(session.today);
			setProject(id);
		}
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
	const previewLines = [...lines, ...parsed];
	const previewCount = new Set(previewLines.flatMap((line) => (line.item_id ? [line.item_id] : [])))
		.size;
	const parsedIncomplete = parsed.filter(
		(line) => !line.item_id || !byId[line.item_id] || !line.quantity || line.quantity <= 0,
	).length;
	const amount = calculateAmount(
		previewLines.map((line) => ({
			quantity: line.quantity,
			rate: line.item_id ? byId[line.item_id]?.rate || 0 : 0,
		})),
	);
	const cents = Math.round(amount * 100),
		each = Math.floor(cents / crew) / 100,
		extra = cents % crew;
	const oldLines: Record<string, number | null> = Object.fromEntries(
		(report?.lines || []).map((l) => [l.item_id, l.quantity]),
	);
	const estimateLines: Record<string, number | null> =
		estimateReport?.date === day && estimateReport.revision >= (report?.revision || 0)
			? Object.fromEntries(estimateReport.lines.map((line) => [line.item_id, line.quantity]))
			: oldLines;
	const nextLines: Record<string, number | null> = Object.fromEntries(
		lines.map((l) => [l.item_id, l.quantity]),
	);
	const deltaIds = [...new Set([...Object.keys(oldLines), ...Object.keys(nextLines)])].filter(
		(id) => oldLines[id] !== nextLines[id],
	);
	const savedNotes = new Map(report?.lines.map((line) => [line.item_id, line.note || '']));
	const notesChanged =
		dayNote.trim() !== (report?.day_note || '') ||
		lines.some((line) => (line.note?.trim() || '') !== (savedNotes.get(line.item_id) || ''));
	const dirty =
		deltaIds.length > 0 ||
		notesChanged ||
		crew !== report?.crew_count ||
		reportText !== report?.text;
	editorState.current = { project, day, dirty: !!report && dirty };
	const currentDraftKey = reportKey(project, day);
	useEffect(() => {
		if (!sessionUserId || isAdmin || !report || reportEditorKey.current !== currentDraftKey) return;
		if (dirty) {
			writeFormDraft(currentDraftKey, {
				revision: report.revision,
				lines,
				crew,
				text: reportText,
				note: dayNote,
			});
		} else if (readFormDraft<ReportDraft>(currentDraftKey)?.revision === report.revision) {
			removeFormDraft(currentDraftKey);
		}
	}, [sessionUserId, isAdmin, report, currentDraftKey, dirty, lines, crew, reportText, dayNote]);
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
	const refreshVisibleTable = useEffectEvent(() => {
		if (
			!document.hidden &&
			!busy &&
			!preview &&
			!document.querySelector('.report-confirmation-modal')
		)
			void refreshBitrix();
	});
	useEffect(() => {
		const refreshOnReturn = () => refreshVisibleTable();
		const timer = window.setInterval(refreshOnReturn, 45000);
		document.addEventListener('visibilitychange', refreshOnReturn);
		window.addEventListener('online', refreshOnReturn);
		return () => {
			window.clearInterval(timer);
			document.removeEventListener('visibilitychange', refreshOnReturn);
			window.removeEventListener('online', refreshOnReturn);
		};
	}, []);
	useEffect(() => {
		setReadingBitrix(false);
		return () => {
			bitrixRead.current?.abort();
			bitrixRead.current = null;
		};
	}, [project, isAdmin]);
	useEffect(() => {
		if (isAdmin || data?.project?.id !== project || data?.config.journal_status !== 'pending')
			return;
		const controller = new AbortController();
		let checking = false;
		const timer = window.setInterval(async () => {
			if (document.hidden || checking) return;
			checking = true;
			try {
				const status = await request<{ journal_status: string; journal_note: string }>(
					'/imports/journal-status',
					undefined,
					project,
					controller.signal,
				);
				if (!controller.signal.aborted)
					setData((current) =>
						current?.project?.id === project
							? { ...current, config: { ...current.config, ...status } }
							: current,
					);
			} catch {
				return;
			} finally {
				checking = false;
			}
		}, 5000);
		return () => {
			controller.abort();
			window.clearInterval(timer);
		};
	}, [project, isAdmin, data?.project?.id, data?.config.journal_status]);
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
								? () => {
										setPage(
											page === 'changes'
												? 'history'
												: ['team', 'reminders'].includes(page)
													? 'more'
													: 'objects',
										);
									}
								: undefined;
	useTelegramNavigation(
		telegramBack,
		(!!report && dirty) || parsed.length > 0 || (textOpen && !!freeText.trim()),
	);
	const valid =
		(lines.length > 0 || !!report?.lines.length || !!dayNote.trim()) &&
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
						note: l.note ?? '',
					})),
					crew_count: crew,
					text: reportText,
					day_note: dayNote,
					allow_exceed: allow,
				},
				project,
			);
			setReport(r);
			setLines(r.lines);
			setDayNote(r.day_note || '');
			removeFormDraft(reportKey(project, day));
			if (r.changed === false) message.info('Изменений нет');
			else if (r.notes_only) message.success('Примечания сохранены');
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
		const workNotes = new Map(lines.map((line) => [line.item_id, line.note ?? '']));
		const notesOnly =
			!freeform &&
			notesChanged &&
			!deltaIds.length &&
			nextCrew === report.crew_count &&
			nextText === report.text;
		const reviewModal = confirmSheet(modal, {
			closable: true,
			title: active ? 'Отчёт · ' + active.name : 'Общий отчёт за день',
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
					estimateLines={estimateLines}
					connected={!!data?.config.has_webhook && data?.config.source === 'bitrix'}
					onValidityChange={(valid, exceeds) =>
						reviewModal.update({
							okText: notesOnly
								? 'Сохранить примечания'
								: exceeds
									? 'Подтвердить перерасход'
									: 'Подтвердить и отправить',
							okButtonProps: { disabled: !valid },
						})
					}
				/>
			),
			okText: notesOnly ? 'Сохранить примечания' : 'Подтвердить и отправить',
			cancelText: 'Вернуться',
			onOk: async () => {
				if (editorState.current.project !== project || editorState.current.day !== day)
					throw new Error('Выбран другой объект. Проверьте отчёт заново.');
				const values = editor.current?.getValues();
				if (!values) throw new Error('Дождитесь открытия отчёта');
				const exceeds = values.lines.some(
					(line) =>
						estimateBalance(byId[line.item_id], estimateLines[line.item_id], line.quantity).excess >
						0,
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
							lines: values.lines.map((line) => ({ ...line, note: workNotes.get(line.item_id) })),
							text: nextText,
							day_note: dayNote,
							allow_exceed: exceeds,
						},
						project,
					);
					setReport(saved);
					setLines(saved.lines);
					setCrew(saved.crew_count);
					setReportText(saved.text || '');
					setDayNote(saved.day_note || '');
					removeFormDraft(reportKey(project, day));
					if (freeform) {
						setTextOpen(false);
						setFreeText('');
					}
					await refresh(true);
					if (saved.notes_only) message.success('Примечания сохранены');
					else if (saved.sync_status === 'synced')
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
	const confirm = () => {
		if (!lines.length && !report?.lines.length && dayNote.trim()) {
			void submit();
			return;
		}
		openReportReview(
			lines.map((line) => ({ item_id: line.item_id!, quantity: line.quantity! })),
			crew,
			reportText,
		);
	};
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
	const updateReportCrew = (count: number | null) => {
		if (count == null) return;
		parsedEditVersion.current++;
		setCrew(count);
		setParsedCrewAmbiguous(false);
	};
	const confirmParsedReport = () => {
		if (!report || !parsed.length || parsedCrewAmbiguous || parsing || busy) {
			if (parsing || busy) return;
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
		openReportReview(next, crew, [reportText, freeText].filter(Boolean).join('\n'), true);
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
			confirmSheet(modal, {
				closable: true,
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
						setDayNote(restored.day_note || '');
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
	const loadUsers = async (quiet = false) => {
		try {
			setUsers(await request<User[]>('/admin/users'));
		} catch (e) {
			if (!quiet) message.error((e as Error).message);
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
			removeFormDraft(objectDraftKey);
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
			removeFormDraft(memberDraftKey);
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
	const retryJournal = async () => {
		setBusy(true);
		try {
			const result = await request<{ status: string; message: string }>(
				'/bitrix/journal',
				{},
				project,
			);
			await loadData(project, true);
			if (result.status === 'ready') message.success(result.message);
			else message.warning(result.message);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
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
	const loadRemoteImport = async (reviewOnly: boolean, original = false, diskBook = false) => {
		if (data?.project?.id !== project) {
			message.info('Дождитесь загрузки выбранного объекта');
			return;
		}
		setBusy(true);
		const selection = selectionVersion.current;
		try {
			if (!reviewOnly && !diskBook) {
				await request('/bitrix/connection', { public_url: url, webhook_id: webhookId }, project);
				setWebhookId(undefined);
			}
			const endpoint = diskBook
				? '/imports/disk-book'
				: original
					? '/imports/bitrix?original=true'
					: '/imports/bitrix';
			const r = await request<ImportPreview | null>(endpoint, {}, project);
			if (selection !== selectionVersion.current) return;
			if (!r) {
				message.success('В исходных листах изменений нет');
				return;
			}
			if (
				!reviewOnly &&
				!diskBook &&
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
	const saveDiskWebhook = async (body: { name?: string; url?: string; project_id?: string }) => {
		const saved = await request<DiskWebhook>('/profile/disk-webhooks', body);
		setDiskWebhooks((current) =>
			current.some((item) => item.id === saved.id) ? current : [...current, saved],
		);
		return saved;
	};
	const updateDiskWebhook = async (id: string, body: { name: string; url: string }) => {
		const saved = await request<DiskWebhook>(
			'/profile/disk-webhooks/' + encodeURIComponent(id) + '/update',
			body,
		);
		setDiskWebhooks((current) => current.map((item) => (item.id === saved.id ? saved : item)));
		return saved;
	};
	const deleteDiskWebhook = async (id: string) => {
		await request('/profile/disk-webhooks/' + encodeURIComponent(id) + '/delete', {});
		setDiskWebhooks((current) => current.filter((item) => item.id !== id));
		setWebhookId((current) => (current === id ? undefined : current));
	};
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
			const result = await request<{ journal: { status: string; message: string } | null }>(
				'/imports/confirm',
				{ token: preview.token, sheets: mapping, acknowledged: ack, ...reconciliation },
				project,
			);
			setPreview(null);
			await refresh();
			if (result.journal?.status === 'pending')
				message.info('Смета сохранена. Рабочие листы готовятся.');
			else if (result.journal && result.journal.status !== 'ready')
				message.warning(result.journal.message);
			else message.success('Таблица готова к работе');
		} catch (e) {
			if (e instanceof RequestError && e.code === 'workbook_changed') await resumeImport();
			else message.error((e as Error).message);
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
			if (error instanceof RequestError && error.code === 'workbook_changed') await resumeImport();
			else message.error((error as Error).message);
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
		retryJournal,
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
		dayNote,
		setDayNote,
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
		parsedCrewAmbiguous,
		patchParsedLine,
		removeParsedLine,
		updateReportCrew,
		previewCount,
		parsedIncomplete,
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
		openUserForm,
		editingUser,
		userId,
		setUserId,
		userName,
		setUserName,
		userRole,
		setUserRole,
		url,
		setUrl,
		webhookId,
		setWebhookId,
		diskWebhooks,
		saveDiskWebhook,
		updateDiskWebhook,
		deleteDiskWebhook,
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
		selectQuickReportProject,
		addLine,
		patchLine,
		amount,
		cents,
		each,
		extra,
		oldLines,
		estimateLines,
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
		importDiskBook: () => loadRemoteImport(false, false, true),
		reviewOriginalTable: () => loadRemoteImport(true, true),
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
