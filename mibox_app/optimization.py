# -*- coding: utf-8 -*-
"""Safe, explicitly scoped device optimization operations."""

from .workers import CancelledError


_ANIMATION_VALUES = (None, '0', '0.5', '1')
_MISSING = object()


def _error_message(exc):
    message = str(exc).strip()
    return message or type(exc).__name__


def analyze(engine, target, check_cancel=lambda: None):
    """Read health and animation settings without changing device state."""
    health = {}
    animations = {}
    warnings = []

    for name, reader, destination in (
            ('health', engine.health, health),
            ('animations', engine.animator_scales, animations)):
        check_cancel()
        try:
            values = reader(target)
            # Preserve exactly the metrics the engine knows; missing or
            # unknown values must not be presented as measured values.
            destination.update(values or {})
        except CancelledError:
            raise
        except Exception as exc:  # A failed probe should not hide the other.
            label = 'Sağlık verileri' if name == 'health' else 'Animasyon ayarları'
            warnings.append('{} okunamadı: {}'.format(label, _error_message(exc)))

    return {'health': health, 'animations': animations, 'warnings': warnings}


def _trim_succeeded(result):
    exit_code = getattr(result, 'exit_code', _MISSING)
    return exit_code is _MISSING or exit_code in (0, '0')


def _trim_message(result):
    exit_code = getattr(result, 'exit_code', _MISSING)
    if exit_code is _MISSING or exit_code in (0, '0'):
        return 'Önbellek temizleme tamamlandı.'
    details = (getattr(result, 'error', None), getattr(result, 'output', None))
    detail = next((str(value).strip() for value in details
                   if value is not None and str(value).strip()),
                  'çıkış kodu {}'.format(exit_code))
    return 'Önbellek temizleme başarısız: {}'.format(detail)


def run_plan(engine, target, trim=False, animation=None,
             check_cancel=lambda: None, progress=lambda cur, total: None):
    """Run only the requested cache trim and/or animation scale change."""
    if animation not in _ANIMATION_VALUES:
        raise ValueError('Animasyon değeri None, "0", "0.5" veya "1" olmalı')

    # Snapshot the call inputs so later UI/Core state changes cannot redirect
    # an in-flight plan to a different device or alter its selected actions.
    selected_target = target
    do_trim = bool(trim)
    selected_animation = animation
    actions = []
    if do_trim:
        actions.append('cache')
    if selected_animation is not None:
        actions.append('animation')
    if not actions:
        raise ValueError('Optimizasyon planı boş olamaz')

    result = {'before': None, 'after': None, 'steps': [], 'cancelled': False}
    try:
        result['before'] = analyze(engine, selected_target, check_cancel)
        total = len(actions)
        for current, action in enumerate(actions, 1):
            # This checkpoint is immediately before the selected operation;
            # no following engine call is made after cancellation is raised.
            check_cancel()
            try:
                if action == 'cache':
                    response = engine.trim_caches(selected_target)
                    ok = _trim_succeeded(response)
                    message = _trim_message(response)
                else:
                    engine.set_animator_scales(
                        selected_target, selected_animation)
                    ok = True
                    message = 'Animasyon ölçekleri {} olarak ayarlandı.'.format(
                        selected_animation)
            except CancelledError:
                raise
            except Exception as exc:
                ok = False
                if action == 'cache':
                    message = 'Önbellek temizleme başarısız: {}'.format(
                        _error_message(exc))
                else:
                    message = 'Animasyon ölçekleri ayarlanamadı: {}'.format(
                        _error_message(exc))

            result['steps'].append({
                'action': action,
                'ok': bool(ok),
                'message': str(message),
            })
            progress(current, total)

        result['after'] = analyze(engine, selected_target, check_cancel)
    except CancelledError:
        result['cancelled'] = True

    return result
