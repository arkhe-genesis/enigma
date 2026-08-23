pub mod phonon;

use thiserror::Error;

pub type HubbleResult<T> = Result<T, HubbleError>;

#[derive(Error, Debug)]
pub enum HubbleError {
    #[error("Phonon error: {0}")]
    Phonon(String),
}
