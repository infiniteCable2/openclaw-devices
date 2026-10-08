// A narrow 16-kHz, 10-ms WebRTC APM boundary for the Pi microphone path.
// The caller serializes capture/render timing through this object. No AGC is
// enabled here: the server owns speech-level regulation.
#include <cstdint>
#include <memory>
#include <mutex>

#include <modules/audio_processing/include/audio_processing.h>

namespace {
constexpr int kSampleRate = 16000;
constexpr int kFrameSamples = 160;

struct AcousticStats {
  int voice_detected;
  int output_rms_dbfs;
  int estimated_delay_ms;
  float residual_echo_likelihood;
};

struct Processor {
  rtc::scoped_refptr<webrtc::AudioProcessing> apm;
  webrtc::StreamConfig stream{kSampleRate, 1};
  webrtc::StreamConfig stereo_stream{kSampleRate, 2};
  std::mutex mutex;
};
}  // namespace

extern "C" {

void* openclaw_apm_create() {
  auto state = std::make_unique<Processor>();
  state->apm = webrtc::AudioProcessingBuilder().Create();
  if (!state->apm) {
    return nullptr;
  }
  webrtc::AudioProcessing::Config config;
  config.echo_canceller.enabled = true;
  config.echo_canceller.mobile_mode = false;
  config.pipeline.multi_channel_capture = true;
  config.noise_suppression.enabled = true;
  config.noise_suppression.level =
      webrtc::AudioProcessing::Config::NoiseSuppression::kModerate;
  config.high_pass_filter.enabled = true;
  config.gain_controller1.enabled = false;
  config.gain_controller2.enabled = false;
  config.voice_detection.enabled = true;
  config.level_estimation.enabled = true;
  state->apm->ApplyConfig(config);
  return state.release();
}

void openclaw_apm_destroy(void* handle) {
  delete static_cast<Processor*>(handle);
}

int openclaw_apm_render(void* handle, const int16_t* samples, int count) {
  if (!handle || !samples || count != kFrameSamples) {
    return -1;
  }
  auto& state = *static_cast<Processor*>(handle);
  std::lock_guard<std::mutex> lock(state.mutex);
  int16_t output[kFrameSamples];
  return state.apm->ProcessReverseStream(samples, state.stream, state.stream, output);
}

int openclaw_apm_capture(void* handle, const int16_t* samples, int count,
                         int delay_ms, int16_t* output) {
  if (!handle || !samples || !output || count != kFrameSamples || delay_ms < 0 ||
      delay_ms > 500) {
    return -1;
  }
  auto& state = *static_cast<Processor*>(handle);
  std::lock_guard<std::mutex> lock(state.mutex);
  const int delay_result = state.apm->set_stream_delay_ms(delay_ms);
  if (delay_result != 0) {
    return delay_result;
  }
  return state.apm->ProcessStream(samples, state.stream, state.stream, output);
}

int openclaw_apm_capture_stereo(void* handle, const int16_t* samples, int count,
                                int delay_ms, int16_t* output) {
  if (!handle || !samples || !output || count != kFrameSamples * 2 || delay_ms < 0 ||
      delay_ms > 500) {
    return -1;
  }
  auto& state = *static_cast<Processor*>(handle);
  std::lock_guard<std::mutex> lock(state.mutex);
  const int delay_result = state.apm->set_stream_delay_ms(delay_ms);
  if (delay_result != 0) {
    return delay_result;
  }
  return state.apm->ProcessStream(samples, state.stereo_stream, state.stream, output);
}

int openclaw_apm_get_stats(void* handle, AcousticStats* output) {
  if (!handle || !output) {
    return -1;
  }
  auto& state = *static_cast<Processor*>(handle);
  std::lock_guard<std::mutex> lock(state.mutex);
  const auto stats = state.apm->GetStatistics();
  output->voice_detected = stats.voice_detected ? (*stats.voice_detected ? 1 : 0) : -1;
  output->output_rms_dbfs = stats.output_rms_dbfs.value_or(-128);
  output->estimated_delay_ms = stats.delay_ms.value_or(-1);
  output->residual_echo_likelihood =
      stats.residual_echo_likelihood ? static_cast<float>(*stats.residual_echo_likelihood) : -1.0f;
  return 0;
}
}
