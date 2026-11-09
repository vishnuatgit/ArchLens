/*
 * ArchLens page behaviour. Plain JavaScript, no build step, no dependencies.
 * Every page works without it; this file adds:
 *
 *  - Theme toggle (saved choice, else the system setting) and the mobile menu
 *  - Toasts:            short confirmations, also read out by screen readers
 *  - Copy buttons:      <button data-copy-text="..."> or <button data-copy-from="#id">
 *  - Example chips:     <button data-fill="psf/requests" data-fill-target="#repo-url">
 *  - Repo validation:   <input data-validate-repo>, same rules as the server
 *  - Live analysis:     <form data-stream="/api/v1/analyze/stream"> streams progress into
 *                       the "How it works" pipeline, then opens the report; with
 *                       data-autostart (a report's "Analyze again") it starts on load
 *  - Busy forms:        <form data-busy-label="Comparing…" data-busy-swap="#results"
 *                       data-busy-skeleton="#skeleton">, plus the compare page's status line
 *  - Tabs, "expand all", dropdown menus, relative times, history filters, compare swap
 */
(function () {
    'use strict';

    var root = document.documentElement;
    var reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function $(selector, scope) { return (scope || document).querySelector(selector); }
    function $all(selector, scope) { return Array.prototype.slice.call((scope || document).querySelectorAll(selector)); }

    var ICONS = {
        check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
        alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5"/><path d="M12 16h.01"/>'
    };
    function svgIcon(name) {
        return '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONS[name] + '</svg>';
    }

    /* ---------- Toasts ---------- */
    var toastRegion = document.getElementById('toasts');

    function toast(message, isError) {
        if (!toastRegion) return;
        var item = document.createElement('div');
        item.className = 'toast' + (isError ? ' toast-error' : '');
        item.innerHTML = svgIcon(isError ? 'alert' : 'check');
        var text = document.createElement('span');
        text.textContent = message;
        item.appendChild(text);
        toastRegion.appendChild(item);
        setTimeout(function () {
            item.classList.add('is-leaving');
            setTimeout(function () { item.remove(); }, 250);
        }, 2600);
    }

    /* ---------- Theme ---------- */
    var themeButton = document.getElementById('theme-toggle');
    var themeMeta = $('meta[name="theme-color"]');

    function applyTheme(theme) {
        root.setAttribute('data-theme', theme);
        var dark = theme === 'dark';
        if (themeButton) themeButton.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
        if (themeMeta) themeMeta.setAttribute('content', dark ? '#070a12' : '#f5f7fb');
    }

    if (themeButton) {
        applyTheme(root.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
        themeButton.addEventListener('click', function () {
            var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
            applyTheme(next);
            try { localStorage.setItem('theme', next); } catch (e) { /* storage blocked */ }
        });
        // Follow the system setting until the visitor picks a theme themselves
        if (window.matchMedia) {
            var query = window.matchMedia('(prefers-color-scheme: light)');
            var follow = function (event) {
                var saved = null;
                try { saved = localStorage.getItem('theme'); } catch (e) { /* storage blocked */ }
                if (!saved) applyTheme(event.matches ? 'light' : 'dark');
            };
            if (query.addEventListener) query.addEventListener('change', follow);
        }
    }

    /* ---------- Mobile menu ---------- */
    var menuButton = document.getElementById('nav-menu');
    var nav = document.getElementById('site-nav');

    function setMenu(open) {
        if (!menuButton || !nav) return;
        nav.classList.toggle('is-open', open);
        menuButton.setAttribute('aria-expanded', String(open));
        menuButton.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    }
    if (menuButton && nav) {
        menuButton.addEventListener('click', function () {
            setMenu(menuButton.getAttribute('aria-expanded') !== 'true');
        });
        document.addEventListener('click', function (event) {
            if (!nav.contains(event.target) && !menuButton.contains(event.target)) setMenu(false);
        });
    }

    /* ---------- Dropdown menus (<details class="menu">) ---------- */
    var menus = $all('details.menu');
    document.addEventListener('click', function (event) {
        menus.forEach(function (menu) {
            if (menu.open && !menu.contains(event.target)) menu.open = false;
        });
    });
    menus.forEach(function (menu) {
        $all('.menu-item', menu).forEach(function (item) {
            item.addEventListener('click', function () { menu.open = false; });
        });
    });

    document.addEventListener('keydown', function (event) {
        if (event.key === 'Escape') {
            setMenu(false);
            menus.forEach(function (menu) {
                if (menu.open) { menu.open = false; $('summary', menu).focus(); }
            });
            return;
        }
        // "/" jumps to the main search or repository field, as on GitHub
        var target = event.target;
        var typing = target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
        if (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
            var field = $('[data-shortcut="/"]');
            if (field) { event.preventDefault(); field.focus(); field.select(); }
        }
    });

    /* ---------- Copy to clipboard ---------- */
    // Fallback for plain-http hosts and browsers that refuse the Clipboard API
    function copyWithTextarea(text) {
        return new Promise(function (resolve, reject) {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', '');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
            document.body.removeChild(area);
            if (ok) { resolve(); } else { reject(new Error('copy failed')); }
        });
    }

    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text).catch(function () { return copyWithTextarea(text); });
        }
        return copyWithTextarea(text);
    }

    function textToCopy(button) {
        if (button.dataset.copyText) return button.dataset.copyText;
        var source = $(button.dataset.copyFrom);
        return source ? (source.value || source.textContent).trim() : '';
    }

    $all('[data-copy-text], [data-copy-from]').forEach(function (button) {
        var label = $('.btn-label', button);
        var original = label ? label.textContent : '';
        button.addEventListener('click', function () {
            // Read the text synchronously so the browser still counts this as a user action
            copyText(textToCopy(button))
                .then(function () {
                    toast(button.dataset.copied || 'Copied to the clipboard');
                    if (label) {
                        label.textContent = 'Copied';
                        setTimeout(function () { label.textContent = original; }, 1600);
                    }
                })
                .catch(function () {
                    toast('Copying failed. Select the text and copy it yourself.', true);
                });
        });
    });

    /* ---------- Repository input: the same rules as app/services/github_service.py ---------- */
    var OWNER = '[A-Za-z0-9][A-Za-z0-9_-]{0,99}';
    var REPO = '[A-Za-z0-9._-]{1,100}';
    var URL_PATTERN = new RegExp('^(?:https?://)?(?:www\\.)?github\\.com/(' + OWNER + ')/(' + REPO + ')(?:[/?#].*)?$', 'i');
    var SLUG_PATTERN = new RegExp('^(' + OWNER + ')/(' + REPO + ')$');

    function parseRepo(value) {
        var text = (value || '').trim().replace(/\/+$/, '');
        if (/\.git$/i.test(text)) text = text.slice(0, -4);
        var match = URL_PATTERN.exec(text) || SLUG_PATTERN.exec(text);
        if (!match || match[2] === '.' || match[2] === '..') return null;
        return match[1] + '/' + match[2];
    }

    function fieldError(input) {
        var id = input.getAttribute('data-error-id');
        return id ? document.getElementById(id) : $('.field-error', input.closest('.field') || input.parentNode);
    }

    function showFieldError(input, message) {
        var box = fieldError(input);
        input.setAttribute('aria-invalid', message ? 'true' : 'false');
        if (!box) return;
        if (message) {
            $('span', box).textContent = message;
            box.hidden = false;
            if (!box.id) box.id = (input.id || 'field') + '-error';
            input.setAttribute('aria-describedby', box.id);
        } else {
            box.hidden = true;
        }
    }

    function validateRepoInput(input) {
        var value = input.value.trim();
        if (!value) {
            showFieldError(input, 'Enter a repository, for example psf/requests.');
            return false;
        }
        if (!parseRepo(value)) {
            showFieldError(input, 'Use owner/repo or a github.com URL, for example https://github.com/psf/requests.');
            return false;
        }
        showFieldError(input, '');
        return true;
    }

    $all('[data-validate-repo]').forEach(function (input) {
        input.addEventListener('input', function () {
            if (input.getAttribute('aria-invalid') === 'true' && parseRepo(input.value)) showFieldError(input, '');
        });
        input.addEventListener('blur', function () {
            if (input.value.trim()) validateRepoInput(input);
        });
    });

    /* ---------- Example chips fill a form field ---------- */
    $all('[data-fill]').forEach(function (chip) {
        chip.addEventListener('click', function () {
            var target = $(chip.dataset.fillTarget);
            if (!target) return;
            target.value = chip.dataset.fill;
            showFieldError(target, '');
            target.focus();
        });
    });

    /* ---------- Busy buttons ---------- */
    function setBusy(button, busy, busyLabel) {
        if (!button) return;
        var label = $('.btn-label', button);
        if (label && !button.dataset.idleLabel) button.dataset.idleLabel = label.textContent;
        button.disabled = busy;
        if (busy) { button.setAttribute('aria-busy', 'true'); } else { button.removeAttribute('aria-busy'); }
        if (label) label.textContent = busy ? (busyLabel || label.textContent) : button.dataset.idleLabel;
    }

    /* ---------- Live analysis: stream progress into the pipeline ---------- */
    var analyzeForm = $('form[data-stream]');
    var canStream = analyzeForm && window.fetch && window.TextDecoder && window.ReadableStream;

    function plural(count, word) { return count + ' ' + word + (count === 1 ? '' : 's'); }

    function ago(seconds) {
        if (seconds < 60) return 'less than a minute ago';
        var minutes = Math.round(seconds / 60);
        return plural(minutes, 'minute') + ' ago';
    }

    function Pipeline(element) {
        this.el = element;
        this.status = $('#pipeline-status', element);
        this.idleStatus = this.status ? this.status.textContent : '';
        this.steps = {};
        var self = this;
        $all('.pipeline-step', element).forEach(function (step) {
            var note = $('[data-note]', step);
            self.steps[step.dataset.step] = { el: step, note: note, idleNote: note ? note.textContent : '' };
        });
    }
    Pipeline.prototype.reset = function () {
        var self = this;
        this.el.setAttribute('data-state', 'idle');
        Object.keys(this.steps).forEach(function (key) {
            var step = self.steps[key];
            step.el.classList.remove('is-active', 'is-done', 'is-failed', 'is-reused');
            if (step.note) step.note.textContent = step.idleNote;
        });
        $all('.step-call', this.el).forEach(function (call) { call.classList.remove('is-done'); });
        this.say(this.idleStatus);
    };
    Pipeline.prototype.say = function (text) { if (this.status) this.status.textContent = text; };
    Pipeline.prototype.state = function (state) { this.el.setAttribute('data-state', state); };
    Pipeline.prototype.note = function (key, text) {
        var step = this.steps[key];
        if (step && step.note) step.note.textContent = text;
    };
    Pipeline.prototype.active = function (key) {
        var step = this.steps[key];
        if (step && !step.el.classList.contains('is-done')) step.el.classList.add('is-active');
    };
    Pipeline.prototype.done = function (key, note) {
        var step = this.steps[key];
        if (!step) return;
        step.el.classList.remove('is-active');
        step.el.classList.add('is-done');
        if (note) this.note(key, note);
    };
    // Marks the step that was running as failed and says why, in a few words
    var FAILURE_NOTES = {
        REPO_NOT_FOUND: 'Repository not found',
        EMPTY_REPOSITORY: 'Repository has no commits',
        RATE_LIMIT_EXCEEDED: 'GitHub quota used up',
        GITHUB_UNAVAILABLE: 'GitHub did not answer'
    };
    Pipeline.prototype.fail = function (code) {
        var self = this;
        var failed = Object.keys(this.steps).filter(function (key) {
            return self.steps[key].el.classList.contains('is-active');
        });
        if (!failed.length) failed = ['fetch'];
        failed.forEach(function (key) {
            var step = self.steps[key].el;
            step.classList.remove('is-active');
            step.classList.add('is-failed');
            // Calls that finished before the failure no longer count as progress
            $all('.step-call', step).forEach(function (call) { call.classList.remove('is-done'); });
            self.note(key, FAILURE_NOTES[code] || 'Stopped');
        });
        this.state('error');
    };
    Pipeline.prototype.tick = function (call) {
        var mark = $('.step-call[data-call="' + call + '"]', this.el);
        if (mark) mark.classList.add('is-done');
    };

    if (canStream) {
        var repoInput = $('[name="url"]', analyzeForm);
        var profileSelect = $('[name="repo_type"]', analyzeForm);
        var submitButton = $('.analyze-btn', analyzeForm) || $('button[type="submit"]', analyzeForm);
        var streamError = $('#stream-error', analyzeForm);
        var serverError = $('#form-error', analyzeForm);
        var pipelineEl = document.getElementById('pipeline');
        var pipeline = pipelineEl ? new Pipeline(pipelineEl) : null;
        var running = false;
        var countdown = null;
        var slowTimer = null;
        var fetchStarted = false;

        repoInput.setAttribute('data-shortcut', '/');
        repoInput.setAttribute('data-error-id', 'repo-error');

        // Events can arrive in one burst when GitHub answers quickly. Each one is still
        // a real step; a short pause between them lets the eye follow the pipeline.
        var queue = [];
        var draining = false;
        function enqueue(event) {
            queue.push(event);
            if (!draining) drain();
        }
        function drain() {
            var event = queue.shift();
            if (!event) { draining = false; return; }
            draining = true;
            handle(event);
            var pause = reducedMotion ? 0 : (event.step === 'fetch' && event.status === 'running' ? 70 : 170);
            setTimeout(drain, pause);
        }

        // GitHub can take several seconds when it is slow or a call is retried; say so
        function watchForSlowGitHub() {
            clearTimeout(slowTimer);
            slowTimer = setTimeout(function () {
                if (!running || fetchStarted || !pipeline) return;
                pipeline.note('fetch', 'Waiting for GitHub…');
                pipeline.say('GitHub is slow to answer. Still trying…');
            }, 4000);
        }

        function handle(event) {
            if (!pipeline) return;
            if (event.event === 'error') { fail(event.error, event); return; }
            if (event.event === 'done') {
                clearTimeout(slowTimer);
                pipeline.state('done');
                if (event.reused && typeof event.score === 'number') pipeline.note('score', 'Stored score: ' + event.score + '/100');
                pipeline.say(event.reused ? 'Opening the stored report…' : 'Report ready. Opening it…');
                setTimeout(function () { window.location.assign(event.report_url); }, reducedMotion ? 0 : 450);
                return;
            }
            switch (event.step) {
                case 'validate':
                    pipeline.say('Reading ' + event.repository + ' from GitHub…');
                    pipeline.active('fetch');
                    break;
                case 'reuse':
                    // Nothing ran this time: mark the steps as reused, not as done
                    clearTimeout(slowTimer);
                    ['fetch', 'analyze', 'score', 'recommend'].forEach(function (key) {
                        pipeline.steps[key].el.classList.remove('is-active');
                        pipeline.steps[key].el.classList.add('is-reused');
                        pipeline.note(key, 'Reused from that report');
                    });
                    pipeline.note('fetch', 'Skipped: analyzed ' + ago(event.age_seconds));
                    pipeline.say('Reusing the report from ' + ago(event.age_seconds) + '. No GitHub calls needed.');
                    break;
                case 'fetch':
                    pipeline.active('fetch');
                    if (event.completed > 0) { fetchStarted = true; clearTimeout(slowTimer); }
                    if (event.call) pipeline.tick(event.call);
                    pipeline.note('fetch', event.completed + ' of ' + event.total + ' API calls done');
                    if (event.status === 'done') {
                        pipeline.done('fetch');
                        pipeline.active('analyze');
                        pipeline.say('Checking seven dimensions…');
                    }
                    break;
                case 'analyze':
                    if (event.status === 'done') {
                        pipeline.done('analyze', plural(event.findings, 'finding') + ' recorded');
                        pipeline.active('score');
                    } else {
                        pipeline.active('analyze');
                    }
                    break;
                case 'score':
                    pipeline.done('score', event.score + '/100, grade ' + event.grade);
                    pipeline.active('recommend');
                    pipeline.say('Scored ' + event.score + '/100. Saving the report…');
                    break;
                case 'save':
                    pipeline.done('recommend', event.suggestions ? plural(event.suggestions, 'next step') : 'Nothing to fix');
                    break;
            }
        }

        function showError(message, event) {
            if (serverError) serverError.hidden = true;
            if (!streamError) return;
            $('[data-error-message]', streamError).textContent = message;
            streamError.hidden = false;
            var retry = $('button[type="submit"]', streamError);
            clearInterval(countdown);
            if (retry) {
                retry.disabled = false;
                var wait = event && event.retry_after;
                // A per-visitor limit says exactly when to come back; count down to it
                if (wait && event.error_code === 'TOO_MANY_ANALYSES') {
                    var left = wait;
                    var tickDown = function () {
                        if (left <= 0) { clearInterval(countdown); retry.disabled = false; retry.lastChild.textContent = 'Try again'; return; }
                        retry.disabled = true;
                        retry.lastChild.textContent = 'Try again in ' + Math.floor(left / 60) + ':' + String(left % 60).padStart(2, '0');
                        left -= 1;
                    };
                    tickDown();
                    countdown = setInterval(tickDown, 1000);
                } else {
                    retry.lastChild.textContent = 'Try again';
                }
            }
        }

        function fail(message, event) {
            running = false;
            clearTimeout(slowTimer);
            setBusy(submitButton, false);
            var code = event && event.error_code;
            if (pipeline && code === 'TOO_MANY_ANALYSES') {
                // Refused before any step ran
                pipeline.reset();
                pipeline.state('error');
                pipeline.say('Not started. Nothing was saved.');
            } else if (pipeline) {
                pipeline.fail(code);
                pipeline.say('Stopped. Nothing was saved.');
            }
            // Problems with what was typed belong next to the field (same codes as the server's)
            if (code === 'REPO_NOT_FOUND' || code === 'INVALID_URL' || code === 'EMPTY_REPOSITORY') {
                showFieldError(repoInput, message);
                repoInput.focus();
                if (streamError) streamError.hidden = true;
                return;
            }
            showError(message, event);
        }

        function readStream(response) {
            var reader = response.body.getReader();
            var decoder = new TextDecoder();
            var buffer = '';
            var finished = false;
            function pump() {
                return reader.read().then(function (chunk) {
                    if (chunk.done) {
                        if (!finished) fail('The connection closed before the analysis finished. Please try again.');
                        return;
                    }
                    buffer += decoder.decode(chunk.value, { stream: true });
                    var lines = buffer.split('\n');
                    buffer = lines.pop();
                    lines.forEach(function (line) {
                        if (!line.trim()) return;
                        var event = JSON.parse(line);
                        if (event.event === 'done' || event.event === 'error') finished = true;
                        enqueue(event);
                    });
                    return pump();
                });
            }
            return pump();
        }

        analyzeForm.addEventListener('submit', function (event) {
            event.preventDefault();
            if (running) return;
            if (!validateRepoInput(repoInput)) { repoInput.focus(); return; }

            running = true;
            fetchStarted = false;
            queue = [];
            watchForSlowGitHub();
            if (streamError) streamError.hidden = true;
            if (serverError) serverError.hidden = true;
            setBusy(submitButton, true, analyzeForm.dataset.busyLabel);
            if (pipeline) {
                pipeline.reset();
                pipeline.state('running');
                pipeline.active('fetch');
                pipeline.say('Checking ' + parseRepo(repoInput.value) + '…');
                // Bring the steps into view when they are off screen (on phones they sit below the form)
                var box = pipeline.el.getBoundingClientRect();
                if (box.top < 64 || box.bottom > window.innerHeight) {
                    pipeline.el.scrollIntoView({ block: 'center', behavior: reducedMotion ? 'auto' : 'smooth' });
                }
            }

            fetch(analyzeForm.dataset.stream, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/x-ndjson' },
                body: JSON.stringify({ url: repoInput.value.trim(), repo_type: profileSelect ? profileSelect.value : 'library' })
            }).then(function (response) {
                if (!response.ok) {
                    return response.json().catch(function () { return {}; }).then(function (body) {
                        var detail = Array.isArray(body.detail) && body.detail[0] ? body.detail[0].msg : null;
                        fail(body.error || detail || 'The server rejected the request (HTTP ' + response.status + ').', body);
                    });
                }
                if (!response.body) { analyzeForm.submit(); return null; }
                return readStream(response);
            }).catch(function () {
                fail('Could not reach ArchLens. The free server may be waking up, which can take about a minute. Try again shortly, or check your connection.');
            });
        });

        // Going Back restores this page from the back/forward cache mid-run; start clean
        window.addEventListener('pageshow', function (event) {
            if (!event.persisted) return;
            running = false;
            clearTimeout(slowTimer);
            setBusy(submitButton, false);
            if (pipeline) pipeline.reset();
        });

        // "Analyze again" on a report links here with ?autostart=1. Only a link from
        // ArchLens itself starts an analysis; the flag is dropped so a reload does not repeat it.
        if (analyzeForm.hasAttribute('data-autostart')) {
            var fromHere = false;
            try { fromHere = !!document.referrer && new URL(document.referrer).origin === location.origin; } catch (e) { fromHere = false; }
            if (window.history && history.replaceState) {
                var clean = new URL(location.href);
                clean.searchParams.delete('autostart');
                history.replaceState(null, '', clean.pathname + clean.search + clean.hash);
            }
            if (fromHere) {
                if (analyzeForm.requestSubmit) { analyzeForm.requestSubmit(); } else { analyzeForm.dispatchEvent(new Event('submit', { cancelable: true })); }
            } else {
                repoInput.focus();
            }
        }
    }

    /* ---------- Compare: say what the server is about to do ---------- */
    // data-stored lists "owner/name:profile" pairs that already have a report; anything
    // else will be analyzed on GitHub, which takes longer and counts towards the limit
    function compareStatus(form) {
        var stored = [];
        try { stored = JSON.parse(form.dataset.stored || '[]'); } catch (e) { stored = []; }
        var profile = ($('[name="profile"]', form) || {}).value || 'library';
        var fresh = $all('[data-validate-repo]', form).map(function (input) {
            return parseRepo(input.value);
        }).filter(function (name) {
            return name && stored.indexOf(name.toLowerCase() + ':' + profile) === -1;
        });
        if (!fresh.length) return 'Loading the two stored reports…';
        return 'Analyzing ' + fresh.join(' and ') + ' on GitHub. This takes a few seconds…';
    }

    /* ---------- Busy state for plain form posts (no streaming) ---------- */
    $all('form[data-busy-label]').forEach(function (form) {
        if (canStream && form === analyzeForm) return;
        var button = $('button[type="submit"]', form);
        var progress = $('[data-progress]', form);

        form.addEventListener('submit', function (event) {
            var invalid = $all('[data-validate-repo]', form).filter(function (input) { return !validateRepoInput(input); });
            if (invalid.length) { event.preventDefault(); invalid[0].focus(); return; }
            // Disable after the browser has collected the form data
            setTimeout(function () { setBusy(button, true, form.dataset.busyLabel); }, 0);
            // Swap the old results for a skeleton while the next page loads
            var results = form.dataset.busySwap && $(form.dataset.busySwap);
            var skeleton = form.dataset.busySkeleton && $(form.dataset.busySkeleton);
            if (results && skeleton) {
                results.hidden = true;
                skeleton.hidden = false;
            }
            if (progress && form.dataset.stored) progress.textContent = compareStatus(form);
        });

        // Going Back restores the page from the back/forward cache with the button still busy
        window.addEventListener('pageshow', function () {
            setBusy(button, false);
            if (progress) progress.textContent = '';
            var results = form.dataset.busySwap && $(form.dataset.busySwap);
            var skeleton = form.dataset.busySkeleton && $(form.dataset.busySkeleton);
            if (results && skeleton) {
                results.hidden = false;
                skeleton.hidden = true;
            }
        });
    });

    /* ---------- Tabs ---------- */
    $all('[role="tablist"]').forEach(function (list) {
        var tabs = $all('[role="tab"]', list);
        function select(tab, focus) {
            tabs.forEach(function (other) {
                var selected = other === tab;
                other.setAttribute('aria-selected', String(selected));
                other.tabIndex = selected ? 0 : -1;
                var panel = document.getElementById(other.getAttribute('aria-controls'));
                if (panel) panel.hidden = !selected;
            });
            if (focus) tab.focus();
        }
        tabs.forEach(function (tab, index) {
            tab.addEventListener('click', function () { select(tab); });
            tab.addEventListener('keydown', function (event) {
                var step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
                if (!step) return;
                event.preventDefault();
                select(tabs[(index + step + tabs.length) % tabs.length], true);
            });
        });
        select(tabs.filter(function (tab) { return tab.getAttribute('aria-selected') === 'true'; })[0] || tabs[0]);
    });

    /* ---------- Expand or collapse every <details> in a group ---------- */
    $all('[data-toggle-details]').forEach(function (button) {
        var group = $(button.dataset.toggleDetails);
        if (!group) return;
        var label = $('.btn-label', button) || button;
        function sync() {
            var all = $all('details', group);
            var open = all.length && all.every(function (d) { return d.open; });
            label.textContent = open ? 'Collapse all' : 'Expand all';
            button.setAttribute('aria-expanded', String(open));
        }
        button.addEventListener('click', function () {
            var all = $all('details', group);
            var open = !all.every(function (d) { return d.open; });
            all.forEach(function (d) { d.open = open; });
            sync();
        });
        group.addEventListener('toggle', sync, true);
        sync();
    });

    // A link to #dimension-key opens that dimension's details
    function openFromHash() {
        if (!location.hash) return;
        var target = document.getElementById(location.hash.slice(1));
        if (target && target.tagName === 'DETAILS') target.open = true;
    }
    window.addEventListener('hashchange', openFromHash);
    openFromHash();

    /* ---------- Relative times: <time datetime="...Z" data-relative> ---------- */
    if (window.Intl && Intl.RelativeTimeFormat) {
        var rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
        var units = [['year', 31536000], ['month', 2592000], ['week', 604800], ['day', 86400], ['hour', 3600], ['minute', 60]];
        $all('time[data-relative]').forEach(function (el) {
            var then = new Date(el.getAttribute('datetime'));
            if (isNaN(then)) return;
            var seconds = (then.getTime() - Date.now()) / 1000;
            var text = 'just now';
            for (var i = 0; i < units.length; i++) {
                if (Math.abs(seconds) >= units[i][1]) { text = rtf.format(Math.round(seconds / units[i][1]), units[i][0]); break; }
            }
            el.title = then.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
            el.textContent = text;
        });
    }

    /* ---------- History: instant filter of this page, auto-submitted selects ---------- */
    var historySearch = document.getElementById('history-search');
    if (historySearch) {
        historySearch.setAttribute('data-shortcut', '/');
        var rows = $all('[data-repo]', document.getElementById('history-list') || document);
        var noMatch = document.getElementById('filter-empty');
        var count = document.getElementById('history-count');
        var countHtml = count ? count.innerHTML : '';
        var serverQuery = historySearch.value.trim().toLowerCase();
        historySearch.addEventListener('input', function () {
            var query = historySearch.value.trim().toLowerCase();
            var shown = 0;
            rows.forEach(function (row) {
                var match = row.dataset.repo.indexOf(query) !== -1;
                row.hidden = !match;
                if (match) shown++;
            });
            if (noMatch) noMatch.hidden = shown !== 0 || !rows.length;
            // The count follows the typing; Enter asks the server to search every report
            if (!count) return;
            if (query === serverQuery) { count.innerHTML = countHtml; return; }
            count.textContent = (query ? shown + ' of ' + rows.length + ' on this page match. ' : '') + 'Press Enter to search every stored report.';
        });
    }
    $all('form[data-autosubmit] select').forEach(function (select) {
        select.addEventListener('change', function () { select.form.submit(); });
    });

    /* ---------- Compare: swap the two repositories ---------- */
    var swap = document.getElementById('swap-repos');
    if (swap) {
        swap.addEventListener('click', function () {
            var a = document.getElementById('compare-a');
            var b = document.getElementById('compare-b');
            var value = a.value;
            a.value = b.value;
            b.value = value;
        });
    }
})();
