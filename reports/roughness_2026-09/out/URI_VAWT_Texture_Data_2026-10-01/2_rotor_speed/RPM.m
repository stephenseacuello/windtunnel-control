clc;
clear;
close all;

%% =========================================================
% 1. CSV 파일 선택
% =========================================================

disp('분석할 CSV 파일을 선택해주세요.');

[file, path] = uigetfile('*.csv', 'CSV 파일 선택');

if isequal(file,0)
    disp('파일 선택이 취소되었습니다.');
    return;
end

csv_filename = fullfile(path,file);

opts = detectImportOptions(csv_filename);
opts.VariableTypes(:) = {'double'};

T = readtable(csv_filename,opts);
M = table2array(T);

disp(['파일 로드 완료: ', file]);


%% =========================================================
% 2. F열 Tachometer만 사용
% =========================================================

Tacho = M(:,6);

Tacho = Tacho(~isnan(Tacho));


%% =========================================================
% 3. Setting RPM
% =========================================================

Setting_RPM = (500:100:1800)';
num_steps = length(Setting_RPM);    % 14단계


%% =========================================================
% 4. Sampling Frequency
% =========================================================

Fs = 359.97;        % Hz

window_time = 5;    % 5초 단위 분석
samples_per_window = round(Fs * window_time);


%% =========================================================
% 5. Tachometer pulse 검출
%
% 실제 CSV 확인 결과:
%
% baseline ≈ -1.5 V
% pulse    ≈ 0 V
%
% 따라서 -0.75 V보다 위로 올라오면 HIGH
% =========================================================

threshold = -0.75;

is_high = Tacho > threshold;

% LOW -> HIGH transition
pulse_idx = find(diff(is_high) == 1) + 1;

fprintf('\nDetected total pulses = %d\n', length(pulse_idx));


%% =========================================================
% 6. 5초 단위 RPM 계산
% =========================================================

num_windows = floor(length(Tacho) / samples_per_window);

RPM_5sec = zeros(num_windows,1);
Pulse_Count_5sec = zeros(num_windows,1);


for w = 1:num_windows

    idx_s = (w-1)*samples_per_window + 1;
    idx_e = w*samples_per_window;

    nPulse = sum( ...
        pulse_idx >= idx_s & ...
        pulse_idx <= idx_e);

    Pulse_Count_5sec(w) = nPulse;

    % 1 pulse = 1 revolution
    RPM_5sec(w) = ...
        nPulse / window_time * 60;

end


%% =========================================================
% 7. 시작/종료의 정지 구간 제거
% =========================================================

running = RPM_5sec > 40;

first_running = find(running,1,'first');

if isempty(first_running)
    error('F열에서 유효한 RPM pulse를 찾지 못했습니다.');
end


% 최대 RPM이 나타나는 지점까지만 사용
% 이후 하강은 실험 종료로 간주
[~, peak_window] = max(RPM_5sec);

RPM_work = RPM_5sec(first_running:peak_window);

window_offset = first_running - 1;


%% =========================================================
% 8. RPM 증가량 계산
%
% 각 Setting 단계가 바뀔 때:
%
% 기존 RPM이 내려가다가
% 다음 단계 시작 시 크게 증가
%
% 따라서 positive jump만 찾음.
% =========================================================

rpm_diff = diff(RPM_work);


%% =========================================================
% 9. 의미 있는 상승점 후보 찾기
%
% 실제 파일에서는 단계 변화가 최소 약 50~60 RPM 이상
% =========================================================

jump_threshold = 40;

candidate = find(rpm_diff > jump_threshold);


%% =========================================================
% 10. 서로 가까운 상승점들을 하나의 transition으로 묶기
%
% 예:
%
% 60 RPM 상승
% 바로 다음 window에 또 60 RPM 상승
%
% 이런 경우 둘 다 같은 단계 변화로 처리
% =========================================================

clusters = {};

if ~isempty(candidate)

    current_cluster = candidate(1);

    c = 1;

    for i = 2:length(candidate)

        % 2 window 이내면 같은 transition
        if candidate(i) - candidate(i-1) <= 2

            current_cluster(end+1) = candidate(i);

        else

            clusters{c} = current_cluster;
            c = c + 1;

            current_cluster = candidate(i);

        end
    end

    clusters{c} = current_cluster;

end


%% =========================================================
% 11. 각 cluster에서 가장 큰 상승점 하나만 선택
% =========================================================

transition_idx = [];

for c = 1:length(clusters)

    temp = clusters{c};

    [~, local_max] = max(rpm_diff(temp));

    transition_idx(end+1,1) = temp(local_max);

end


%% =========================================================
% 12. 첫 시작 직후 / 마지막 종료 후 가짜 transition 제거
% =========================================================

% 첫 RPM plateau가 시작된 뒤 최소 4 window 이후부터
transition_idx = transition_idx(transition_idx >= 4);

% 최대점보다 앞에 있는 변화만 사용
transition_idx = ...
    transition_idx(transition_idx < length(RPM_work));


%% =========================================================
% 13. 정확히 13개의 단계 변화 선택
%
% 500 -> 600 -> ... -> 1800
% 총 14단계이므로 경계는 13개
% =========================================================

if length(transition_idx) > num_steps-1

    % 상승량이 큰 13개 선택
    jump_size = rpm_diff(transition_idx);

    [~, order] = sort(jump_size,'descend');

    transition_idx = ...
        transition_idx(order(1:num_steps-1));

    transition_idx = sort(transition_idx);

end


if length(transition_idx) < num_steps-1

    warning(['13개의 RPM 단계 변화를 모두 찾지 못했습니다. ', ...
             '현재 검출 개수 = ', ...
             num2str(length(transition_idx))]);

end


%% =========================================================
% 14. Stage boundary 생성
%
% diff(j)는 j -> j+1 사이 변화이므로
% 새로운 단계는 j+1에서 시작
% =========================================================

boundaries = [ ...
    1; ...
    transition_idx + 1; ...
    length(RPM_work)+1];


%% =========================================================
% 15. 각 단계별 실제 Tachometer RPM 계산
%
% 5초 RPM 자체의 mode가 아니라
% 원래 pulse 간격으로 RPM을 계산한 뒤
% 5 RPM 단위로 묶어서 최빈값 사용
% =========================================================

Measured_RPM = NaN(num_steps,1);
Pulse_Count = zeros(num_steps,1);


for k = 1:min(num_steps,length(boundaries)-1)

    %% 이 단계가 원본 데이터의 어느 sample 구간인지 계산

    window_start = ...
        boundaries(k) + window_offset;

    window_end = ...
        boundaries(k+1)-1 + window_offset;


    sample_start = ...
        (window_start-1)*samples_per_window + 1;

    sample_end = ...
        min(window_end*samples_per_window, length(Tacho));


    %% 해당 단계 안의 pulse
    stage_pulse_idx = pulse_idx( ...
        pulse_idx >= sample_start & ...
        pulse_idx <= sample_end);


    Pulse_Count(k) = length(stage_pulse_idx);


    if length(stage_pulse_idx) < 3
        continue;
    end


    %% pulse 사이 시간
    sample_interval = diff(stage_pulse_idx);

    pulse_dt = sample_interval / Fs;


    %% 1 pulse = 1 revolution
    rpm_each = 60 ./ pulse_dt;


    %% 명백한 오류 제거
    rpm_each = rpm_each( ...
        rpm_each >= 20 & ...
        rpm_each <= 1000);


    if isempty(rpm_each)
        continue;
    end


   %% 1 RPM 단위로 반올림
rpm_rounded = round(rpm_each);

%% 가장 빈도수가 높은 실제 RPM
Measured_RPM(k) = mode(rpm_rounded);

end


%% =========================================================
% 16. 결과 테이블
% =========================================================

RPM_Table = table( ...
    Setting_RPM, ...
    Measured_RPM, ...
    Pulse_Count);


disp(' ');
disp('======================================');
disp('          RPM Analysis Result');
disp('======================================');

disp(RPM_Table);


%% =========================================================
% 17. 원본 파일명 + "_summary.csv" 로 저장
% =========================================================

if ispc

    desktop_path = ...
        fullfile(getenv('USERPROFILE'),'Desktop');

else

    desktop_path = ...
        fullfile(getenv('HOME'),'Desktop');

end


% 원본 filename에서 확장자 제거
[~, original_name, ~] = fileparts(file);

% 원본명_summary.csv
summary_filename = ...
    [original_name, '_summary.csv'];


output_file = fullfile( ...
    desktop_path, ...
    summary_filename);


writetable(RPM_Table, output_file);


fprintf('\n======================================\n');
fprintf('CSV 저장 완료\n');
fprintf('%s\n', output_file);
fprintf('======================================\n');


%% =========================================================
% 18. 5초 RPM 그래프
% =========================================================

figure(1);

set(gcf, ...
    'Color','w', ...
    'Position',[100 100 1200 550]);


plot( ...
    RPM_5sec, ...
    '-o', ...
    'LineWidth',1.5, ...
    'MarkerSize',5);

hold on;


%% 검출된 단계 경계 표시

for k = 2:length(boundaries)-1

    x = boundaries(k) + window_offset;

    xline( ...
        x, ...
        '--', ...
        'LineWidth',1.5);

end


grid on;

xlabel('5-sec Window');
ylabel('Measured RPM');

title('RPM from Column F');


%% =========================================================
% 19. Setting RPM vs Measured RPM
% =========================================================

figure(2);

set(gcf, ...
    'Color','w', ...
    'Position',[150 150 750 550]);


plot( ...
    Setting_RPM, ...
    Measured_RPM, ...
    '-o', ...
    'LineWidth',2, ...
    'MarkerSize',8);


grid on;

xlabel('Setting RPM');
ylabel('Measured RPM');

title('Setting RPM vs Measured RPM');